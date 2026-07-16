import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType


SUPPORTED_SCHEMA_VERSION = 1
_REQUIRED_FIELDS = (
    "package_id",
    "region",
    "start_at",
    "end_at",
    "schema_version",
    "algorithm_config_version",
    "files",
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class ReplayManifestInvalid(ValueError):
    """Raised when a replay manifest does not satisfy its schema."""


@dataclass(frozen=True, slots=True)
class ReplayManifest:
    package_id: str
    region: tuple[float, float, float, float]
    start_at: datetime
    end_at: datetime
    schema_version: int
    algorithm_config_version: str
    files: Mapping[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.schema_version, int) or isinstance(
            self.schema_version, bool
        ):
            raise ReplayManifestInvalid("schema_version must be an integer")
        if self.schema_version != SUPPORTED_SCHEMA_VERSION:
            raise ReplayManifestInvalid(
                f"unsupported schema_version: {self.schema_version}"
            )
        _nonblank_string(self.package_id, "package_id")
        _nonblank_string(
            self.algorithm_config_version,
            "algorithm_config_version",
        )
        _require_utc(self.start_at, "start_at")
        _require_utc(self.end_at, "end_at")
        if self.end_at < self.start_at:
            raise ReplayManifestInvalid("end_at must not precede start_at")
        _validate_bbox(self.region)
        object.__setattr__(self, "files", _validated_files(self.files))

    @classmethod
    def load(cls, path: Path) -> "ReplayManifest":
        try:
            raw_payload: object = json.loads(
                _read_manifest(path),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ReplayManifestInvalid(f"{path.name} is not valid JSON") from error
        except OSError as error:
            raise ReplayManifestInvalid(f"cannot read {path.name}: {error}") from error

        if not isinstance(raw_payload, Mapping):
            raise ReplayManifestInvalid("manifest must be a JSON object")
        payload = _string_keyed_mapping(raw_payload, "manifest")
        for field in _REQUIRED_FIELDS:
            if field not in payload:
                raise ReplayManifestInvalid(f"missing required field: {field}")
        unsupported = sorted(payload.keys() - set(_REQUIRED_FIELDS))
        if unsupported:
            raise ReplayManifestInvalid(f"unsupported manifest field: {unsupported[0]}")

        return cls(
            package_id=payload["package_id"],  # type: ignore[arg-type]
            region=_region(payload["region"]),
            start_at=_strict_utc_timestamp(payload["start_at"], "start_at"),
            end_at=_strict_utc_timestamp(payload["end_at"], "end_at"),
            schema_version=payload["schema_version"],  # type: ignore[arg-type]
            algorithm_config_version=payload[  # type: ignore[arg-type]
                "algorithm_config_version"
            ],
            files=_files(payload["files"]),
        )


def _read_manifest(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ReplayManifestInvalid(f"{path.name} must be a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as file:
            return file.read()
    finally:
        os.close(descriptor)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ReplayManifestInvalid(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> object:
    raise ReplayManifestInvalid(f"invalid JSON number: {value}")


def _string_keyed_mapping(
    value: Mapping[object, object], field: str
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ReplayManifestInvalid(f"{field} keys must be strings")
        result[key] = item
    return result


def _nonblank_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReplayManifestInvalid(f"{field} must be a nonblank string")
    return value


def _strict_utc_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ReplayManifestInvalid(f"{field} must be an ISO-8601 timestamp")
    if value.endswith("-00:00"):
        raise ReplayManifestInvalid(f"{field} must be UTC")
    try:
        parsed = datetime.fromisoformat(
            f"{value[:-1]}+00:00" if value.endswith("Z") else value
        )
    except ValueError:
        raise ReplayManifestInvalid(f"{field} must be an ISO-8601 timestamp") from None
    _require_utc(parsed, field)
    return parsed


def _require_utc(value: object, field: str) -> None:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ReplayManifestInvalid(f"{field} must be UTC")


def _region(value: object) -> tuple[float, float, float, float]:
    if not isinstance(value, Mapping):
        raise ReplayManifestInvalid("region.bbox must contain four coordinates")
    region = _string_keyed_mapping(value, "region")
    unsupported = sorted(region.keys() - {"bbox"})
    if unsupported:
        raise ReplayManifestInvalid(f"unsupported region field: {unsupported[0]}")
    bbox = region.get("bbox")
    if (
        not isinstance(bbox, Sequence)
        or isinstance(bbox, (str, bytes, bytearray))
        or len(bbox) != 4
    ):
        raise ReplayManifestInvalid("region.bbox must contain four coordinates")
    parsed = tuple(_finite_number(item, "region.bbox") for item in bbox)
    return parsed[0], parsed[1], parsed[2], parsed[3]


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReplayManifestInvalid(f"{field} coordinates must be finite numbers")
    parsed = float(value)
    if not isfinite(parsed):
        raise ReplayManifestInvalid(f"{field} coordinates must be finite numbers")
    return parsed


def _validate_bbox(bbox: object) -> None:
    if not isinstance(bbox, tuple) or len(bbox) != 4:
        raise ReplayManifestInvalid("region.bbox must contain four coordinates")
    west, south, east, north = (_finite_number(value, "region.bbox") for value in bbox)
    if not -180 <= west <= 180 or not -180 <= east <= 180:
        raise ReplayManifestInvalid("region.bbox longitudes are outside valid range")
    if not -90 <= south <= 90 or not -90 <= north <= 90:
        raise ReplayManifestInvalid("region.bbox latitudes are outside valid range")
    if west >= east or south >= north:
        raise ReplayManifestInvalid(
            "region.bbox must have west < east and south < north"
        )


def _files(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise ReplayManifestInvalid("files must be a nonempty object")
    raw_files = _string_keyed_mapping(value, "files")
    return {filename: digest for filename, digest in raw_files.items()}  # type: ignore[misc]


def _validated_files(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise ReplayManifestInvalid("files must be a nonempty object")
    validated: dict[str, str] = {}
    for raw_filename, raw_digest in value.items():
        if not isinstance(raw_filename, str) or not _is_safe_relative_path(
            raw_filename
        ):
            raise ReplayManifestInvalid(f"unsafe file path: {raw_filename}")
        if (
            not isinstance(raw_digest, str)
            or _SHA256_PATTERN.fullmatch(raw_digest) is None
        ):
            raise ReplayManifestInvalid(f"files[{raw_filename}] must be a SHA-256")
        validated[raw_filename] = raw_digest
    return MappingProxyType(validated)


def _is_safe_relative_path(value: str) -> bool:
    if not value or value != value.strip() or "\\" in value or "\x00" in value:
        return False
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    return (
        not posix_path.is_absolute()
        and not windows_path.is_absolute()
        and not windows_path.drive
        and posix_path.as_posix() == value
        and all(part not in {"", ".", ".."} for part in posix_path.parts)
    )
