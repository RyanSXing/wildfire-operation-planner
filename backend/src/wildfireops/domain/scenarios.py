from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RoadClosure:
    edge_id: str


@dataclass(frozen=True, slots=True)
class WeatherOverride:
    wind_speed_mps: float
    wind_direction_degrees: float

    def __post_init__(self) -> None:
        if self.wind_speed_mps < 0:
            raise ValueError("wind speed cannot be negative")
        if not 0 <= self.wind_direction_degrees < 360:
            raise ValueError("wind direction is outside valid range")


@dataclass(frozen=True, slots=True)
class ResourceOverride:
    resource_id: str
    available: bool


@dataclass(frozen=True, slots=True)
class ScenarioVersion:
    scenario_id: str
    version: int
    incident_snapshot_id: str
    road_closures: tuple[RoadClosure, ...]
    weather_overrides: tuple[WeatherOverride, ...]
    resource_overrides: tuple[ResourceOverride, ...]

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("scenario version must be positive")
