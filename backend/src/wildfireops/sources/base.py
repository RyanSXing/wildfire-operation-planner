from dataclasses import dataclass
from typing import Protocol

from wildfireops.domain.observations import (
    FrozenJsonObject,
    SourceObservation,
    freeze_json_object,
)


@dataclass(frozen=True, slots=True)
class SourceValidationFailure:
    source_name: str
    reason: str
    raw_payload: FrozenJsonObject

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_payload", freeze_json_object(self.raw_payload))


@dataclass(frozen=True, slots=True)
class SourceBatch:
    observations: tuple[SourceObservation, ...]
    failures: tuple[SourceValidationFailure, ...]


class SourceAdapter(Protocol):
    @property
    def source_name(self) -> str:
        raise NotImplementedError

    async def fetch(self) -> SourceBatch:
        raise NotImplementedError
