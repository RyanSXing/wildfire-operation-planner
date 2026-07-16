import argparse
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from math import isfinite
from pathlib import Path

from wildfireops.domain.observations import (
    FrozenJsonValue,
    NormalizedObservation,
    SourceObservation,
    WeatherObservation,
)
from wildfireops.replay.loader import (
    ReplayLoader,
    ReplayPackageCorrupt,
    _OBSERVATION_FILE_TYPES,
    _parse_observation,
    _split_jsonl,
    _validate_scope,
)
from wildfireops.replay.manifest import (
    SUPPORTED_SCHEMA_VERSION,
    ReplayManifest,
    ReplayManifestInvalid,
)


_OBSERVATION_FILENAMES = (
    "fire_detections.jsonl",
    "weather_observations.jsonl",
)
_STATIC_DATA_FILENAME = "static_data_versions.json"
_CITATIONS_FILENAME = "source_citations.json"
_OUTPUT_FILENAMES = (
    *_OBSERVATION_FILENAMES,
    _STATIC_DATA_FILENAME,
    _CITATIONS_FILENAME,
)
_METADATA_FIELDS = {
    "algorithm_config_version",
    "static_data_versions",
    "source_citations",
}


class ReplayBuildError(ValueError):
    """Raised when staged replay data cannot produce a valid package."""


@dataclass(frozen=True, slots=True)
class _BuildMetadata:
    algorithm_config_version: str
    static_data_versions: dict[str, str]
    source_citations: dict[str, str]


def build_package(
    *,
    source_dir: Path,
    package_id: str,
    bbox: tuple[float, float, float, float],
    start_at: datetime,
    end_at: datetime,
    output: Path,
) -> Path:
    try:
        return _build_package(
            source_dir=source_dir,
            package_id=package_id,
            bbox=bbox,
            start_at=start_at,
            end_at=end_at,
            output=output,
        )
    except ReplayBuildError:
        raise
    except (OSError, ReplayManifestInvalid, ReplayPackageCorrupt) as error:
        raise ReplayBuildError(str(error)) from error


def _build_package(
    *,
    source_dir: Path,
    package_id: str,
    bbox: tuple[float, float, float, float],
    start_at: datetime,
    end_at: datetime,
    output: Path,
) -> Path:
    source_dir = Path(source_dir)
    output = Path(output)
    _validate_paths(source_dir, output)
    metadata = _load_metadata(_read_staged_file(source_dir, "metadata.json"))
    manifest_template = _manifest(
        package_id=package_id,
        bbox=bbox,
        start_at=start_at,
        end_at=end_at,
        algorithm_config_version=metadata.algorithm_config_version,
        files={filename: "0" * 64 for filename in _OUTPUT_FILENAMES},
    )
    observations = _load_staged_observations(source_dir, manifest_template)
    contents = {
        "fire_detections.jsonl": _encode_observations(
            observations["fire_detections.jsonl"]
        ),
        "weather_observations.jsonl": _encode_observations(
            observations["weather_observations.jsonl"]
        ),
        _STATIC_DATA_FILENAME: _canonical_json(metadata.static_data_versions),
        _CITATIONS_FILENAME: _canonical_json(metadata.source_citations),
    }
    for filename, content in contents.items():
        if not content:
            raise ReplayBuildError(f"required output would be empty: {filename}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}.tmp-",
            dir=output.parent,
        )
    )
    try:
        for filename in _OUTPUT_FILENAMES:
            _atomic_write(temporary / filename, contents[filename])
        hashes = {
            filename: _sha256_file(temporary / filename)
            for filename in _OUTPUT_FILENAMES
        }
        manifest = _manifest(
            package_id=package_id,
            bbox=bbox,
            start_at=start_at,
            end_at=end_at,
            algorithm_config_version=metadata.algorithm_config_version,
            files=hashes,
        )
        manifest_payload = {
            "package_id": manifest.package_id,
            "region": {"bbox": list(manifest.region)},
            "start_at": _format_timestamp(manifest.start_at),
            "end_at": _format_timestamp(manifest.end_at),
            "schema_version": manifest.schema_version,
            "algorithm_config_version": manifest.algorithm_config_version,
            "files": dict(manifest.files),
        }
        _atomic_write(temporary / "manifest.json", _canonical_json(manifest_payload))
        ReplayLoader(temporary)
        _publish(temporary, output)
    except (OSError, ReplayManifestInvalid, ReplayPackageCorrupt) as error:
        raise ReplayBuildError(str(error)) from error
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return output


def _validate_paths(source_dir: Path, output: Path) -> None:
    if source_dir.is_symlink() or not source_dir.is_dir():
        raise ReplayBuildError("source_dir must be a nonsymlink directory")
    source_resolved = source_dir.resolve()
    output_resolved = output.resolve(strict=False)
    if (
        source_resolved == output_resolved
        or source_resolved in output_resolved.parents
        or output_resolved in source_resolved.parents
    ):
        raise ReplayBuildError(
            "source_dir and output must be distinct and nonoverlapping"
        )
    if output.is_symlink():
        raise ReplayBuildError("output must not be a symlink")
    if output.exists():
        if not output.is_dir():
            raise ReplayBuildError("output must be a directory path")
        if any(output.iterdir()):
            raise ReplayBuildError("output directory must be empty")


def _read_staged_file(source_dir: Path, filename: str) -> bytes:
    path = source_dir / filename
    if path.is_symlink():
        raise ReplayBuildError(f"staged file must not be a symlink: {filename}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ReplayBuildError(f"staged path is not a file: {filename}")
            with os.fdopen(descriptor, "rb", closefd=False) as file:
                content = file.read()
        finally:
            os.close(descriptor)
    except ReplayBuildError:
        raise
    except OSError as error:
        raise ReplayBuildError(
            f"cannot read staged file {filename}: {error}"
        ) from error
    if not content:
        raise ReplayBuildError(f"staged file must not be empty: {filename}")
    return content


def _load_metadata(content: bytes) -> _BuildMetadata:
    try:
        raw_payload: object = json.loads(
            content,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except _MetadataInvalid as error:
        raise ReplayBuildError(f"invalid metadata.json: {error}") from None
    except ValueError as error:
        raise ReplayBuildError("metadata.json is not valid JSON") from error
    if not isinstance(raw_payload, Mapping):
        raise ReplayBuildError("metadata.json must be an object")
    payload = _string_object(raw_payload, "metadata.json")
    missing = sorted(_METADATA_FIELDS - payload.keys())
    if missing:
        raise ReplayBuildError(f"metadata.json missing required field: {missing[0]}")
    unsupported = sorted(payload.keys() - _METADATA_FIELDS)
    if unsupported:
        raise ReplayBuildError(f"metadata.json has unsupported field: {unsupported[0]}")
    return _BuildMetadata(
        algorithm_config_version=_nonblank(
            payload["algorithm_config_version"],
            "algorithm_config_version",
        ),
        static_data_versions=_nonempty_string_map(
            payload["static_data_versions"],
            "static_data_versions",
        ),
        source_citations=_nonempty_string_map(
            payload["source_citations"],
            "source_citations",
        ),
    )


class _MetadataInvalid(ValueError):
    pass


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _MetadataInvalid(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> object:
    raise _MetadataInvalid(f"invalid JSON number: {value}")


def _string_object(value: Mapping[object, object], field: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ReplayBuildError(f"{field} keys must be strings")
        result[key] = item
    return result


def _nonblank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReplayBuildError(f"{field} must be a nonblank string")
    return value


def _nonempty_string_map(value: object, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise ReplayBuildError(f"{field} must be a nonempty object")
    result: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = _nonblank(raw_key, f"{field} key")
        if (
            key in {".", ".."}
            or "/" in key
            or "\\" in key
            or "\x00" in key
            or key != key.strip()
        ):
            raise ReplayBuildError(f"unsafe {field} key: {key}")
        result[key] = _nonblank(raw_value, f"{field}[{key}]")
    return result


def _manifest(
    *,
    package_id: str,
    bbox: tuple[float, float, float, float],
    start_at: datetime,
    end_at: datetime,
    algorithm_config_version: str,
    files: Mapping[str, str],
) -> ReplayManifest:
    try:
        return ReplayManifest(
            package_id=package_id,
            region=bbox,
            start_at=start_at,
            end_at=end_at,
            schema_version=SUPPORTED_SCHEMA_VERSION,
            algorithm_config_version=algorithm_config_version,
            files=files,
        )
    except ReplayManifestInvalid as error:
        raise ReplayBuildError(str(error)) from error


def _load_staged_observations(
    source_dir: Path,
    manifest: ReplayManifest,
) -> dict[str, tuple[SourceObservation, ...]]:
    observations: dict[str, tuple[SourceObservation, ...]] = {}
    identities: set[str] = set()
    for filename in _OBSERVATION_FILENAMES:
        content = _read_staged_file(source_dir, filename)
        try:
            records = _split_jsonl(content.decode("utf-8"))
        except UnicodeDecodeError:
            raise ReplayBuildError(f"{filename} is not valid UTF-8") from None
        if not records:
            raise ReplayBuildError(f"staged file must contain records: {filename}")
        parsed: list[SourceObservation] = []
        for line_number, serialized in enumerate(records, start=1):
            try:
                observation = _parse_observation(
                    serialized,
                    filename,
                    line_number,
                    _OBSERVATION_FILE_TYPES[filename],
                )
                _validate_scope(observation, manifest, filename, line_number)
            except ReplayPackageCorrupt as error:
                raise ReplayBuildError(str(error)) from error
            if observation.identity in identities:
                raise ReplayBuildError(
                    f"{filename}:{line_number}: duplicate source identity: "
                    f"{observation.identity}"
                )
            identities.add(observation.identity)
            parsed.append(observation)
        observations[filename] = tuple(
            sorted(parsed, key=lambda item: (item.observed_at, item.identity))
        )
    return observations


def _encode_observations(observations: tuple[SourceObservation, ...]) -> bytes:
    return b"".join(
        _canonical_json(_observation_payload(item)) for item in observations
    )


def _observation_payload(observation: SourceObservation) -> dict[str, object]:
    common: dict[str, object] = {
        "source_name": observation.source_name,
        "source_record_id": observation.source_record_id,
        "observed_at": _format_timestamp(observation.observed_at),
        "longitude": observation.longitude,
        "latitude": observation.latitude,
        "raw_payload": _materialize_json(observation.raw_payload),
    }
    if isinstance(observation, NormalizedObservation):
        return {
            "observation_type": "fire_detection",
            **common,
            "confidence": observation.confidence,
            "intensity": observation.intensity,
        }
    if isinstance(observation, WeatherObservation):
        return {
            "observation_type": "weather_observation",
            **common,
            "wind_speed_mps": observation.wind_speed_mps,
            "wind_direction_degrees": observation.wind_direction_degrees,
            "temperature_celsius": observation.temperature_celsius,
        }
    raise ReplayBuildError("unsupported observation domain type")


def _materialize_json(value: FrozenJsonValue) -> object:
    if isinstance(value, Mapping):
        return {key: _materialize_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_materialize_json(item) for item in value]
    return value


def _canonical_json(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _format_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as file:
        file.write(content)
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _publish(temporary: Path, output: Path) -> None:
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise ReplayBuildError("output directory must remain empty until publish")
    os.replace(temporary, output)


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Canonicalize recorded normalized observations into an offline replay."
    )
    parser.add_argument(
        "--source-dir",
        required=True,
        type=Path,
        help=(
            "read-only staging directory containing recorded normalized observations "
            "in fire_detections.jsonl and weather_observations.jsonl, plus metadata.json "
            "fields algorithm_config_version, static_data_versions, and source_citations"
        ),
    )
    parser.add_argument("--package-id", required=True)
    parser.add_argument(
        "--bbox",
        required=True,
        type=_bbox_argument,
        metavar="WEST,SOUTH,EAST,NORTH",
    )
    parser.add_argument("--start", required=True, type=_utc_timestamp_argument)
    parser.add_argument("--end", required=True, type=_utc_timestamp_argument)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def _bbox_argument(value: str) -> tuple[float, float, float, float]:
    parts = value.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must contain west,south,east,north")
    try:
        bbox = tuple(float(part) for part in parts)
    except (OverflowError, ValueError):
        raise argparse.ArgumentTypeError(
            "bbox coordinates must be finite numbers"
        ) from None
    if not all(isfinite(item) for item in bbox):
        raise argparse.ArgumentTypeError("bbox coordinates must be finite numbers")
    return bbox[0], bbox[1], bbox[2], bbox[3]


def _utc_timestamp_argument(value: str) -> datetime:
    if value.endswith("-00:00"):
        raise argparse.ArgumentTypeError(
            "timestamp must be ISO-8601 with a zero UTC offset"
        )
    try:
        parsed = datetime.fromisoformat(
            f"{value[:-1]}+00:00" if value.endswith("Z") else value
        )
    except ValueError:
        raise argparse.ArgumentTypeError(
            "timestamp must be ISO-8601 with a zero UTC offset"
        ) from None
    if parsed.utcoffset() != timedelta(0):
        raise argparse.ArgumentTypeError(
            "timestamp must be ISO-8601 with a zero UTC offset"
        )
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = _argument_parser()
    arguments = parser.parse_args(argv)
    try:
        build_package(
            source_dir=arguments.source_dir,
            package_id=arguments.package_id,
            bbox=arguments.bbox,
            start_at=arguments.start,
            end_at=arguments.end,
            output=arguments.output,
        )
    except ReplayBuildError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
