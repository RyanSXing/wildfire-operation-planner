"""Deterministic replay seed identity, serialization, and command."""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from hashlib import sha256
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

from geoalchemy2.elements import WKTElement
from shapely.geometry import shape  # type: ignore[import-untyped]
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.config import get_settings
from wildfireops.db import create_engine, create_session_factory
from wildfireops.decision.risk import RiskConfig
from wildfireops.geospatial.clustering import ClusteringConfig
from wildfireops.geospatial.clustering import cluster_detections
from wildfireops.geospatial.exposure import ExposureConfig
from wildfireops.ingestion.worker import build_exposure_config, build_risk_config
from wildfireops.persistence.exposures import refresh_exposure_and_risk
from wildfireops.persistence.incidents import (
    acquire_incident_refresh_lock,
    load_current_fire_detections,
    refresh_incidents,
)
from wildfireops.persistence.observations import ObservationRepository
from wildfireops.persistence.observed_models import (
    ExposedAssetModel,
    QuarantinedObservationModel,
    ResourceUnitModel,
    SourceObservationModel,
    SourceStatusModel,
    WildfireIncidentModel,
    materialize_json_object,
)
from wildfireops.persistence.scenarios import ScenarioRepository
from wildfireops.replay.loader import ReplayLoader, ReplayPackageCorrupt
from wildfireops.replay.manifest import ReplayManifest


type SessionFactory = Callable[[], AsyncSession]


_PROTECTED_TABLES = (
    ("source_observations", SourceObservationModel.id),
    ("quarantined_observations", QuarantinedObservationModel.id),
    ("exposed_assets", ExposedAssetModel.id),
    ("resource_units", ResourceUnitModel.id),
    ("wildfire_incidents", WildfireIncidentModel.id),
    ("source_status", SourceStatusModel.id),
)


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


async def seed_replay_package(
    *,
    loader: ReplayLoader,
    session_factory: SessionFactory,
    clustering_config: ClusteringConfig,
    exposure_config: ExposureConfig,
    risk_config: RiskConfig,
) -> ReplaySeedResult:
    static_data = loader.static_data
    if static_data is None:
        raise ReplaySeedError("replay seed requires a complete static data package")
    observations = tuple(loader.iter_until(loader.manifest.end_at))
    package_digest = _package_digest(loader.manifest)
    request_hash = _seed_request_hash(
        package_digest,
        clustering_config,
        exposure_config,
        risk_config,
    )

    async with session_factory() as session:
        async with session.begin():
            await acquire_incident_refresh_lock(session)
            claim = await ScenarioRepository(session).claim_idempotency(
                scope="replay_seed",
                key=loader.manifest.package_id,
                request_hash=request_hash,
            )
            if not claim.created:
                if claim.request_hash != request_hash:
                    raise ReplaySeedConflict(
                        "replay package_id already seeded with different contents "
                        f"or settings: {loader.manifest.package_id}"
                    )
                return ReplaySeedResult(
                    package_id=loader.manifest.package_id,
                    package_digest=package_digest,
                    status="already_seeded",
                    assets_inserted=0,
                    resources_inserted=0,
                    observations_inserted=0,
                    incidents_created=0,
                    snapshots_created=0,
                )
            for table_name, column in _PROTECTED_TABLES:
                if await session.scalar(select(column).limit(1)) is not None:
                    raise ReplaySeedConflict(
                        f"database contains operational data in {table_name}"
                    )

            session.add_all(
                [
                    ExposedAssetModel(
                        asset_id=item.asset_id,
                        asset_kind=item.asset_kind,
                        name=item.name,
                        population=item.population,
                        capacity=item.capacity,
                        source_name=item.source_name,
                        source_version=item.source_version,
                        geometry=WKTElement(
                            shape(item.geometry_geojson).wkt, srid=4326
                        ),
                        raw_metadata=materialize_json_object(item.raw_metadata),
                    )
                    for item in sorted(
                        static_data.assets, key=lambda item: item.asset_id
                    )
                ]
            )
            session.add_all(
                [
                    ResourceUnitModel(
                        resource_id=item.resource_id,
                        resource_type=item.resource_type,
                        capabilities=list(item.capabilities),
                        capacity=item.capacity,
                        available=item.available,
                        status=item.status,
                        geometry=WKTElement(
                            shape(item.geometry_geojson).wkt, srid=4326
                        ),
                        raw_metadata=materialize_json_object(item.raw_metadata),
                    )
                    for item in sorted(
                        static_data.resources,
                        key=lambda item: item.resource_id,
                    )
                ]
            )
            stats = await ObservationRepository().upsert_many(session, observations)
            if stats.deduplicated:
                raise ReplaySeedError(
                    "replay seed observations must not be deduplicated"
                )
            await session.flush()
            detections = await load_current_fire_detections(
                session,
                reference_at=loader.manifest.end_at,
                temporal_window_seconds=clustering_config.temporal_window_seconds,
            )
            clusters = cluster_detections(detections, clustering_config)
            if not clusters:
                raise ReplaySeedError("replay seed produced no incident clusters")
            await refresh_incidents(
                session,
                clusters,
                clustering_config.spatial_radius_meters,
            )
            await session.flush()
            incidents_created = int(
                await session.scalar(
                    select(func.count()).select_from(WildfireIncidentModel)
                )
                or 0
            )
            snapshot_ids = await refresh_exposure_and_risk(
                session,
                reference_at=loader.manifest.end_at,
                exposure_config=exposure_config,
                risk_config=risk_config,
                clustering_algorithm_version=clustering_config.algorithm_version,
            )
            for source_name in sorted({item.source_name for item in observations}):
                source_observations = [
                    item for item in observations if item.source_name == source_name
                ]
                session.add(
                    SourceStatusModel(
                        source_name=source_name,
                        outcome="success",
                        last_attempted_at=loader.manifest.end_at,
                        last_success_at=max(
                            item.observed_at for item in source_observations
                        ),
                        accepted_count=len(source_observations),
                        deduplicated_count=0,
                        quarantined_count=0,
                        error_message=None,
                    )
                )
            return ReplaySeedResult(
                package_id=loader.manifest.package_id,
                package_digest=package_digest,
                status="seeded",
                assets_inserted=len(static_data.assets),
                resources_inserted=len(static_data.resources),
                observations_inserted=stats.inserted,
                incidents_created=incidents_created,
                snapshots_created=len(snapshot_ids),
            )


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed an offline replay package.")
    parser.add_argument("package", type=Path, metavar="PACKAGE")
    return parser


async def _async_main(package: Path) -> int:
    settings = get_settings()
    loader = ReplayLoader(package)
    engine = create_engine(settings)
    try:
        result = await seed_replay_package(
            loader=loader,
            session_factory=create_session_factory(engine),
            clustering_config=ClusteringConfig(
                spatial_radius_meters=settings.clustering_spatial_radius_meters,
                temporal_window_seconds=settings.clustering_temporal_window_seconds,
                minimum_points=settings.clustering_minimum_points,
                algorithm_version=settings.clustering_algorithm_version,
            ),
            exposure_config=build_exposure_config(settings),
            risk_config=build_risk_config(settings),
        )
        print(_result_json(result))
        return 0
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    package = _argument_parser().parse_args(argv).package
    try:
        return asyncio.run(_async_main(package))
    except (ReplayPackageCorrupt, ReplaySeedError) as error:
        print(f"replay seed failed: {error}", file=sys.stderr)
    except Exception as error:
        print(f"replay seed failed: {type(error).__name__}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
