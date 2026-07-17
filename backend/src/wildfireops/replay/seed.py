"""Deterministic replay seed identity and result serialization."""

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Literal

from wildfireops.decision.risk import RiskConfig
from wildfireops.geospatial.clustering import ClusteringConfig
from wildfireops.geospatial.exposure import ExposureConfig
from wildfireops.replay.manifest import ReplayManifest


class ReplaySeedError(ValueError):
    """Raised when a replay package cannot produce valid seeded state."""


class ReplaySeedConflict(ReplaySeedError):
    """Raised when replay state is already owned by another seed request."""


@dataclass(frozen=True, slots=True)
class ReplaySeedResult:
    package_id: str
    package_digest: str
    status: Literal["seeded", "already_seeded"]
    assets_inserted: int
    resources_inserted: int
    observations_inserted: int
    incidents_created: int
    snapshots_created: int


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _package_digest(manifest: ReplayManifest) -> str:
    return sha256(_canonical_json(manifest.to_payload())).hexdigest()


def _seed_request_payload(
    package_digest: str,
    clustering_config: ClusteringConfig,
    exposure_config: ExposureConfig,
    risk_config: RiskConfig,
) -> dict[str, object]:
    return {
        "package_digest": package_digest,
        "clustering_config": asdict(clustering_config),
        "exposure_config": asdict(exposure_config),
        "risk_config": asdict(risk_config),
    }


def _seed_request_hash(
    package_digest: str,
    clustering_config: ClusteringConfig,
    exposure_config: ExposureConfig,
    risk_config: RiskConfig,
) -> str:
    payload = _seed_request_payload(
        package_digest,
        clustering_config,
        exposure_config,
        risk_config,
    )
    return sha256(_canonical_json(payload)).hexdigest()


def _result_json(result: ReplaySeedResult) -> str:
    return _canonical_json(asdict(result)).decode("utf-8")
