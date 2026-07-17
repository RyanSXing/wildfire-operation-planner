import json
import os
import stat
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from math import isfinite
from pathlib import Path

from wildfireops.domain.observations import (
    FrozenJsonObject,
    NormalizedObservation,
    SourceObservation,
    WeatherObservation,
    freeze_json_object,
)
from wildfireops.replay.manifest import ReplayManifest, ReplayManifestInvalid
from wildfireops.replay.static_data import (
    STATIC_DATA_FILENAMES,
    ReplayStaticData,
    ReplayStaticDataInvalid,
    parse_replay_static_data,
)


_OBSERVATION_FILE_TYPES = {
    "fire_detections.jsonl": "fire_detection",
    "weather_observations.jsonl": "weather_observation",
}
_COMMON_FIELDS = {
    "observation_type",
    "source_name",
    "source_record_id",
    "observed_at",
    "longitude",
    "latitude",
    "raw_payload",
}
_FIRE_FIELDS = _COMMON_FIELDS | {"confidence", "intensity"}
_WEATHER_FIELDS = _COMMON_FIELDS | {
    "wind_speed_mps",
    "wind_direction_degrees",
    "temperature_celsius",
}


class ReplayPackageCorrupt(ValueError):
    """Raised when replay package contents do not match their manifest."""


class ReplayRecordInvalid(ReplayPackageCorrupt):
    """Raised when a replay JSONL record cannot be decoded."""


class _RecordDataInvalid(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _ReplayRecord:
    observed_at: datetime
    identity: str
    serialized: str
    filename: str
    line_number: int


@dataclass(frozen=True, slots=True)
class _HashedFile:
    digest: str
    content: bytes


class ReplayLoader:
    def __init__(self, package: Path) -> None:
        if package.is_symlink() or not package.is_dir():
            raise ReplayPackageCorrupt("replay package must be a directory")
        manifest_path = package / "manifest.json"
        if manifest_path.is_symlink():
            raise ReplayPackageCorrupt("manifest.json must not be a symlink")
        try:
            self.manifest = ReplayManifest.load(manifest_path)
        except ReplayManifestInvalid as error:
            raise ReplayPackageCorrupt(f"invalid manifest: {error}") from error

        file_contents: dict[str, bytes] = {}
        for filename, expected_hash in self.manifest.files.items():
            path = _referenced_file(package, filename)
            hashed_file = _sha256_file(path)
            if not hashed_file.content:
                raise ReplayPackageCorrupt(f"empty referenced file: {filename}")
            if hashed_file.digest != expected_hash:
                raise ReplayPackageCorrupt(f"hash mismatch for {filename}")
            file_contents[filename] = hashed_file.content

        self.static_data: ReplayStaticData | None
        if any(
            filename in file_contents
            for filename in ("exposed_assets.geojson", "resources.json")
        ):
            try:
                self.static_data = parse_replay_static_data(
                    {
                        filename: file_contents[filename]
                        for filename in STATIC_DATA_FILENAMES
                        if filename in file_contents
                    },
                    self.manifest,
                )
            except ReplayStaticDataInvalid as error:
                raise ReplayPackageCorrupt(str(error)) from error
        else:
            self.static_data = None

        observation_files = [
            filename for filename in file_contents if filename.endswith(".jsonl")
        ]
        if not observation_files:
            raise ReplayPackageCorrupt("replay package has no observation JSONL files")
        for filename in observation_files:
            if filename not in _OBSERVATION_FILE_TYPES:
                raise ReplayPackageCorrupt(f"unsupported observation file: {filename}")

        records: list[_ReplayRecord] = []
        identities: set[str] = set()
        observation_sources: set[str] = set()
        for filename in observation_files:
            try:
                serialized_records = _split_jsonl(
                    file_contents[filename].decode("utf-8")
                )
            except UnicodeDecodeError:
                raise ReplayRecordInvalid(
                    f"{filename}:1: file is not valid UTF-8"
                ) from None
            if not serialized_records:
                raise ReplayPackageCorrupt(
                    f"observation file contains no records: {filename}"
                )
            for line_number, serialized in enumerate(serialized_records, start=1):
                observation = _parse_observation(
                    serialized,
                    filename,
                    line_number,
                    _OBSERVATION_FILE_TYPES[filename],
                )
                _validate_scope(
                    observation,
                    self.manifest,
                    filename,
                    line_number,
                )
                if observation.identity in identities:
                    raise ReplayRecordInvalid(
                        f"{filename}:{line_number}: duplicate source identity: "
                        f"{observation.identity}"
                    )
                identities.add(observation.identity)
                observation_sources.add(observation.source_name)
                records.append(
                    _ReplayRecord(
                        observed_at=observation.observed_at,
                        identity=observation.identity,
                        serialized=serialized,
                        filename=filename,
                        line_number=line_number,
                    )
                )
        if self.static_data is not None:
            for source_name in sorted(observation_sources):
                if source_name not in self.static_data.static_data_versions:
                    raise ReplayPackageCorrupt(
                        f"missing static data version for observation source: "
                        f"{source_name}"
                    )
                if source_name not in self.static_data.source_citations:
                    raise ReplayPackageCorrupt(
                        f"missing source citation for observation source: {source_name}"
                    )
        self._records = tuple(
            sorted(records, key=lambda record: (record.observed_at, record.identity))
        )

    def iter_until(self, at: datetime) -> Iterator[SourceObservation]:
        if not isinstance(at, datetime) or at.utcoffset() != timedelta(0):
            raise ValueError("at must be UTC")
        return (
            _parse_observation(
                record.serialized,
                record.filename,
                record.line_number,
                _OBSERVATION_FILE_TYPES[record.filename],
            )
            for record in self._records
            if record.observed_at <= at
        )


def _referenced_file(package: Path, filename: str) -> Path:
    current = package
    for part in Path(filename).parts:
        current /= part
        if current.is_symlink():
            raise ReplayPackageCorrupt(
                f"referenced file must not be a symlink: {filename}"
            )
    if not current.exists():
        raise ReplayPackageCorrupt(f"missing referenced file: {filename}")
    if not current.is_file():
        raise ReplayPackageCorrupt(f"referenced path is not a file: {filename}")
    return current


def _sha256_file(path: Path) -> _HashedFile:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ReplayPackageCorrupt(
                    f"referenced path is not a file: {path.name}"
                )
            content = bytearray()
            digest = sha256()
            with os.fdopen(descriptor, "rb", closefd=False) as file:
                for chunk in iter(lambda: file.read(1024 * 1024), b""):
                    content.extend(chunk)
                    digest.update(chunk)
        finally:
            os.close(descriptor)
    except ReplayPackageCorrupt:
        raise
    except OSError as error:
        raise ReplayPackageCorrupt(
            f"cannot read referenced file {path.name}: {error}"
        ) from error
    return _HashedFile(digest=digest.hexdigest(), content=bytes(content))


def _split_jsonl(content: str) -> list[str]:
    records = content.split("\n")
    if records and records[-1] == "":
        records.pop()
    return records


def _parse_observation(
    serialized: str,
    filename: str,
    line_number: int,
    expected_type: str,
) -> SourceObservation:
    context = f"{filename}:{line_number}"
    if not serialized.strip():
        raise ReplayRecordInvalid(f"{context}: record must not be blank")
    try:
        raw_payload: object = json.loads(
            serialized,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        payload = _record_object(raw_payload, "record")
        observation_type = _required_string(payload, "observation_type")
        if observation_type not in _OBSERVATION_FILE_TYPES.values():
            raise _RecordDataInvalid(
                f"unsupported observation_type: {observation_type}"
            )
        if observation_type != expected_type:
            raise _RecordDataInvalid(
                f"observation_type must be {expected_type} in {filename}"
            )
        if observation_type == "fire_detection":
            return _fire_observation(payload)
        return _weather_observation(payload)
    except json.JSONDecodeError:
        raise ReplayRecordInvalid(f"{context}: invalid JSON") from None
    except _RecordDataInvalid as error:
        raise ReplayRecordInvalid(f"{context}: {error}") from None
    except (AttributeError, KeyError, OverflowError, TypeError, ValueError) as error:
        raise ReplayRecordInvalid(f"{context}: {error}") from None


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _RecordDataInvalid(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> object:
    raise _RecordDataInvalid(f"invalid JSON number: {value}")


def _record_object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise _RecordDataInvalid(f"{field} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise _RecordDataInvalid(f"{field} keys must be strings")
        result[key] = item
    return result


def _validate_fields(payload: Mapping[str, object], expected: set[str]) -> None:
    missing = sorted(expected - payload.keys())
    if missing:
        raise _RecordDataInvalid(f"missing required field: {missing[0]}")
    unsupported = sorted(payload.keys() - expected)
    if unsupported:
        raise _RecordDataInvalid(f"unsupported field: {unsupported[0]}")


def _required_string(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _RecordDataInvalid(f"{field} must be a nonblank string")
    return value


def _strict_utc_timestamp(payload: Mapping[str, object]) -> datetime:
    value = payload.get("observed_at")
    if not isinstance(value, str):
        raise _RecordDataInvalid("observed_at must be an ISO-8601 timestamp")
    if value.endswith("-00:00"):
        raise _RecordDataInvalid("observed_at must be UTC")
    try:
        parsed = datetime.fromisoformat(
            f"{value[:-1]}+00:00" if value.endswith("Z") else value
        )
    except ValueError:
        raise _RecordDataInvalid("observed_at must be an ISO-8601 timestamp") from None
    if parsed.utcoffset() != timedelta(0):
        raise _RecordDataInvalid("observed_at must be UTC")
    return parsed


def _finite_number(payload: Mapping[str, object], field: str) -> float:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _RecordDataInvalid(f"{field} must be a finite number")
    try:
        parsed = float(value)
    except OverflowError:
        raise _RecordDataInvalid(f"{field} must be a finite number") from None
    if not isfinite(parsed):
        raise _RecordDataInvalid(f"{field} must be a finite number")
    return parsed


def _optional_number(payload: Mapping[str, object], field: str) -> float | None:
    if payload.get(field) is None:
        return None
    return _finite_number(payload, field)


def _raw_payload(payload: Mapping[str, object]) -> FrozenJsonObject:
    value = payload.get("raw_payload")
    if not isinstance(value, Mapping):
        raise _RecordDataInvalid("raw_payload must be an object")
    return freeze_json_object(_record_object(value, "raw_payload"))


def _fire_observation(payload: Mapping[str, object]) -> NormalizedObservation:
    _validate_fields(payload, _FIRE_FIELDS)
    return NormalizedObservation(
        source_name=_required_string(payload, "source_name"),
        source_record_id=_required_string(payload, "source_record_id"),
        observed_at=_strict_utc_timestamp(payload),
        longitude=_finite_number(payload, "longitude"),
        latitude=_finite_number(payload, "latitude"),
        confidence=_finite_number(payload, "confidence"),
        intensity=_optional_number(payload, "intensity"),
        raw_payload=_raw_payload(payload),
    )


def _weather_observation(payload: Mapping[str, object]) -> WeatherObservation:
    _validate_fields(payload, _WEATHER_FIELDS)
    return WeatherObservation(
        source_name=_required_string(payload, "source_name"),
        source_record_id=_required_string(payload, "source_record_id"),
        observed_at=_strict_utc_timestamp(payload),
        longitude=_finite_number(payload, "longitude"),
        latitude=_finite_number(payload, "latitude"),
        wind_speed_mps=_finite_number(payload, "wind_speed_mps"),
        wind_direction_degrees=_finite_number(
            payload,
            "wind_direction_degrees",
        ),
        temperature_celsius=_optional_number(payload, "temperature_celsius"),
        raw_payload=_raw_payload(payload),
    )


def _validate_scope(
    observation: SourceObservation,
    manifest: ReplayManifest,
    filename: str,
    line_number: int,
) -> None:
    context = f"{filename}:{line_number}"
    if not manifest.start_at <= observation.observed_at <= manifest.end_at:
        raise ReplayRecordInvalid(
            f"{context}: observation is outside manifest time range"
        )
    west, south, east, north = manifest.region
    if not (
        west <= observation.longitude <= east and south <= observation.latitude <= north
    ):
        raise ReplayRecordInvalid(
            f"{context}: observation is outside manifest region.bbox"
        )
