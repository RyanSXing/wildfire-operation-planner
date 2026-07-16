import argparse
import asyncio
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Protocol
from urllib.parse import quote
from uuid import uuid4

import httpx
import structlog

from wildfireops.config import Settings, get_settings
from wildfireops.db import create_engine, create_session_factory
from wildfireops.geospatial.clustering import ClusteringConfig
from wildfireops.ingestion.service import IngestionRun, IngestionService
from wildfireops.observability import configure_observability
from wildfireops.replay.loader import ReplayLoader
from wildfireops.sources.base import SourceAdapter, SourceBatch
from wildfireops.sources.firms import FirmsAdapter
from wildfireops.sources.nws import NwsAdapter


class IngestionRunner(Protocol):
    async def run_source(self, adapter: SourceAdapter) -> IngestionRun:
        raise NotImplementedError


class EventLogger(Protocol):
    def info(self, event: str, **values: object) -> object:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ScheduledSource:
    adapter: SourceAdapter
    interval_seconds: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.interval_seconds, bool)
            or not isinstance(self.interval_seconds, (int, float))
            or not isfinite(self.interval_seconds)
            or self.interval_seconds <= 0
        ):
            raise ValueError("interval_seconds must be a finite positive number")


class ReplayAdapter:
    def __init__(self, loader: ReplayLoader) -> None:
        self._loader = loader

    @property
    def source_name(self) -> str:
        return f"replay:{self._loader.manifest.package_id}"

    async def fetch(self) -> SourceBatch:
        return SourceBatch(
            observations=tuple(self._loader.iter_until(self._loader.manifest.end_at)),
            failures=(),
            reference_at=self._loader.manifest.end_at,
        )


def build_live_adapters(
    settings: Settings,
    client: httpx.AsyncClient,
) -> tuple[ScheduledSource, ...]:
    sources: list[ScheduledSource] = []
    if settings.firms_map_key is not None:
        map_key = quote(settings.firms_map_key.get_secret_value(), safe="")
        firms_url = "/".join(
            (
                settings.firms_area_url.rstrip("/"),
                map_key,
                quote(settings.firms_source, safe=""),
                quote(settings.firms_bbox, safe=",.-"),
                str(settings.firms_day_range),
            )
        )
        sources.append(
            ScheduledSource(
                adapter=FirmsAdapter(client, httpx.Request("GET", firms_url)),
                interval_seconds=settings.firms_poll_interval_seconds,
            )
        )
    sources.append(
        ScheduledSource(
            adapter=NwsAdapter(
                client,
                httpx.Request("GET", settings.nws_observation_url),
                settings.nws_user_agent,
            ),
            interval_seconds=settings.nws_poll_interval_seconds,
        )
    )
    return tuple(sources)


async def run_once(
    service: IngestionRunner,
    sources: Sequence[ScheduledSource],
    *,
    logger: EventLogger | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    job_id_factory: Callable[[], str] = lambda: str(uuid4()),
) -> int:
    event_logger = logger or structlog.get_logger("wildfireops.ingestion")
    outcomes = [
        await _run_source(
            service,
            scheduled.adapter,
            logger=event_logger,
            monotonic=monotonic,
            job_id_factory=job_id_factory,
        )
        for scheduled in sources
    ]
    return int(not outcomes or all(outcome == "failed" for outcome in outcomes))


async def run_replay(
    package: Path,
    service: IngestionRunner,
    *,
    logger: EventLogger | None = None,
) -> int:
    adapter = ReplayAdapter(ReplayLoader(package))
    event_logger = logger or structlog.get_logger("wildfireops.ingestion")
    outcome = await _run_source(service, adapter, logger=event_logger)
    return int(outcome == "failed")


async def run_forever(
    service: IngestionRunner,
    sources: Sequence[ScheduledSource],
    *,
    logger: EventLogger | None = None,
) -> None:
    if not sources:
        raise ValueError("at least one configured source is required")
    event_logger = logger or structlog.get_logger("wildfireops.ingestion")

    async def poll(scheduled: ScheduledSource) -> None:
        while True:
            await _run_source(service, scheduled.adapter, logger=event_logger)
            await asyncio.sleep(scheduled.interval_seconds)

    await asyncio.gather(*(poll(source) for source in sources))


async def _run_source(
    service: IngestionRunner,
    adapter: SourceAdapter,
    *,
    logger: EventLogger,
    monotonic: Callable[[], float] = time.monotonic,
    job_id_factory: Callable[[], str] = lambda: str(uuid4()),
) -> str:
    started_at = monotonic()
    try:
        result = await service.run_source(adapter)
    except Exception:
        result = IngestionRun(
            source_name=adapter.source_name,
            accepted=0,
            deduplicated=0,
            quarantined=0,
            outcome="failed",
        )
    duration_ms = max(0, round((monotonic() - started_at) * 1_000))
    logger.info(
        "ingestion_run",
        job_id=job_id_factory(),
        source_name=result.source_name,
        accepted=result.accepted,
        deduplicated=result.deduplicated,
        quarantined=result.quarantined,
        duration_ms=duration_ms,
        outcome=result.outcome,
    )
    return result.outcome


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run WildfireOps ingestion")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--once",
        action="store_true",
        help="poll every configured live source once and exit",
    )
    modes.add_argument(
        "--replay",
        type=Path,
        metavar="PACKAGE",
        help="ingest one offline replay package and exit",
    )
    return parser


async def _async_main(arguments: argparse.Namespace) -> int:
    settings = get_settings()
    configure_observability(settings.environment)
    engine = create_engine(settings)
    service = IngestionService(
        create_session_factory(engine),
        ClusteringConfig(
            spatial_radius_meters=settings.clustering_spatial_radius_meters,
            temporal_window_seconds=settings.clustering_temporal_window_seconds,
            minimum_points=settings.clustering_minimum_points,
            algorithm_version=settings.clustering_algorithm_version,
        ),
    )
    try:
        if arguments.replay is not None:
            return await run_replay(arguments.replay, service)
        async with httpx.AsyncClient() as client:
            sources = build_live_adapters(settings, client)
            if arguments.once:
                return await run_once(service, sources)
            await run_forever(service, sources)
            return 0
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_async_main(_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
