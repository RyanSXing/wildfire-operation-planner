"""Immutable values used by bounded PostGIS exposure analysis."""

from dataclasses import dataclass
from math import isfinite

from wildfireops.domain.observations import FrozenJsonObject, freeze_json_object


MIN_EXPOSURE_BUFFER_METERS = 100.0
MAX_EXPOSURE_BUFFER_METERS = 100_000.0


@dataclass(frozen=True, slots=True)
class ExposureConfig:
    buffer_meters: float = 10_000.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "buffer_meters",
            validate_buffer_meters(self.buffer_meters),
        )


@dataclass(frozen=True, slots=True)
class ExposedAssetExposure:
    asset_id: str
    asset_kind: str
    name: str
    population: int | None
    capacity: int | None
    source_name: str | None
    source_version: str | None
    geometry_geojson: FrozenJsonObject
    raw_metadata: FrozenJsonObject
    distance_meters: float
    bearing_degrees: float | None

    def __post_init__(self) -> None:
        for field in ("asset_id", "asset_kind", "name"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be a nonblank string")
            object.__setattr__(self, field, value.strip())
        for field in ("source_name", "source_version"):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{field} must be null or a nonblank string")
            if value is not None:
                object.__setattr__(self, field, value.strip())
        for field in ("population", "capacity"):
            value = getattr(self, field)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int)
            ):
                raise ValueError(f"{field} must be null or an integer")
        object.__setattr__(
            self,
            "distance_meters",
            _finite_nonnegative(self.distance_meters, "distance_meters"),
        )
        if self.bearing_degrees is not None:
            bearing = _finite_number(self.bearing_degrees, "bearing_degrees")
            if not 0.0 <= bearing < 360.0:
                raise ValueError("bearing_degrees must be in [0, 360)")
            object.__setattr__(self, "bearing_degrees", bearing)
        object.__setattr__(
            self,
            "geometry_geojson",
            freeze_json_object(self.geometry_geojson),
        )
        object.__setattr__(
            self,
            "raw_metadata",
            freeze_json_object(self.raw_metadata),
        )


def validate_buffer_meters(value: object) -> float:
    parsed = _finite_number(value, "buffer_meters")
    if not MIN_EXPOSURE_BUFFER_METERS <= parsed <= MAX_EXPOSURE_BUFFER_METERS:
        raise ValueError(
            "buffer_meters must be between 100 and 100000 meters inclusive"
        )
    return parsed


def _finite_nonnegative(value: object, field: str) -> float:
    parsed = _finite_number(value, field)
    if parsed < 0:
        raise ValueError(f"{field} must be finite and nonnegative")
    return parsed


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    try:
        parsed = float(value)
    except (OverflowError, ValueError):
        raise ValueError(f"{field} must be a finite number") from None
    if not isfinite(parsed):
        raise ValueError(f"{field} must be a finite number")
    return parsed
