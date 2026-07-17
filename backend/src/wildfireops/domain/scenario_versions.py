from dataclasses import dataclass
from uuid import UUID

from wildfireops.domain.scenarios import ScenarioVersion


class PinnedSnapshotInvalid(ValueError):
    """Raised when persisted snapshot resource JSON is malformed."""


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    id: UUID
    request_hash: str
    response_type: str | None
    response_id: UUID | None
    created: bool


@dataclass(frozen=True, slots=True)
class PinnedIncidentSnapshot:
    id: UUID
    resource_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class StoredScenarioVersion:
    version_id: UUID
    incident_id: UUID
    graph_version: str
    scenario: ScenarioVersion
