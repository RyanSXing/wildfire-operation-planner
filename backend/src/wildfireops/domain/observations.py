from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from types import MappingProxyType


type FrozenJsonScalar = None | bool | int | float | str
type FrozenJsonValue = (
    FrozenJsonScalar | Mapping[str, FrozenJsonValue] | tuple[FrozenJsonValue, ...]
)
type FrozenJsonObject = Mapping[str, FrozenJsonValue]


def freeze_json_value(value: object) -> FrozenJsonValue:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(
                "raw_payload contains unsupported JSON value: non-finite float"
            )
        return value
    if isinstance(value, Mapping):
        return freeze_json_object(value)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(freeze_json_value(item) for item in value)
    raise ValueError(
        f"raw_payload contains unsupported JSON value: {type(value).__name__}"
    )


def freeze_json_object(payload: Mapping[str, object]) -> FrozenJsonObject:
    frozen: dict[str, FrozenJsonValue] = {}
    for key, value in payload.items():
        if not isinstance(key, str):
            raise ValueError("raw_payload mapping keys must be strings")
        frozen[key] = freeze_json_value(value)
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True)
class NormalizedObservation:
    source_name: str
    source_record_id: str
    observed_at: datetime
    longitude: float
    latitude: float
    confidence: float
    intensity: float | None
    raw_payload: FrozenJsonObject

    def __post_init__(self) -> None:
        if not self.source_name or not self.source_record_id:
            raise ValueError("source identity is required")
        if self.observed_at.utcoffset() != timedelta(0):
            raise ValueError("observed_at must be UTC")
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude is outside valid range")
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude is outside valid range")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence is outside valid range")
        object.__setattr__(self, "raw_payload", freeze_json_object(self.raw_payload))

    @property
    def identity(self) -> str:
        return f"{self.source_name}:{self.source_record_id}"


@dataclass(frozen=True, slots=True)
class WeatherObservation:
    source_name: str
    source_record_id: str
    observed_at: datetime
    longitude: float
    latitude: float
    wind_speed_mps: float
    wind_direction_degrees: float
    temperature_celsius: float | None
    raw_payload: FrozenJsonObject

    def __post_init__(self) -> None:
        if not self.source_name or not self.source_record_id:
            raise ValueError("source identity is required")
        if self.observed_at.utcoffset() != timedelta(0):
            raise ValueError("observed_at must be UTC")
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude is outside valid range")
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude is outside valid range")
        if self.wind_speed_mps < 0:
            raise ValueError("wind speed cannot be negative")
        if not 0 <= self.wind_direction_degrees < 360:
            raise ValueError("wind direction is outside valid range")
        object.__setattr__(self, "raw_payload", freeze_json_object(self.raw_payload))

    @property
    def identity(self) -> str:
        return f"{self.source_name}:{self.source_record_id}"


SourceObservation = NormalizedObservation | WeatherObservation
