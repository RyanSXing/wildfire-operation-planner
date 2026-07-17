from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResourceUnit:
    resource_id: str
    capabilities: frozenset[str]
    capacity: int
    available: bool
    longitude: float
    latitude: float

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            raise ValueError("resource capacity must be positive")
        if not self.capabilities:
            raise ValueError("resource capabilities are required")


@dataclass(frozen=True, slots=True)
class DemandPoint:
    destination_id: str
    required_capability: str
    required_capacity: int
    weighted_risk: float
    longitude: float
    latitude: float

    def __post_init__(self) -> None:
        if self.required_capacity <= 0:
            raise ValueError("required capacity must be positive")
        if self.weighted_risk < 0:
            raise ValueError("weighted risk cannot be negative")
