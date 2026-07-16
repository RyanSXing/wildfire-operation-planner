from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class NormalizedObservation:
    source_name: str
    source_record_id: str
    observed_at: datetime
    longitude: float
    latitude: float
    confidence: float
    intensity: float | None
    raw_payload: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.source_name or not self.source_record_id:
            raise ValueError("source identity is required")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude is outside valid range")
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude is outside valid range")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence is outside valid range")

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
    raw_payload: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.source_name or not self.source_record_id:
            raise ValueError("source identity is required")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude is outside valid range")
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude is outside valid range")
        if self.wind_speed_mps < 0:
            raise ValueError("wind speed cannot be negative")
        if not 0 <= self.wind_direction_degrees < 360:
            raise ValueError("wind direction is outside valid range")

    @property
    def identity(self) -> str:
        return f"{self.source_name}:{self.source_record_id}"


SourceObservation = NormalizedObservation | WeatherObservation
