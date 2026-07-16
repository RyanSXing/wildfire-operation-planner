from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from wildfireops.config import Settings
from wildfireops.ingestion.service import IngestionRun
from wildfireops.ingestion.worker import (
    ScheduledSource,
    build_live_adapters,
    run_once,
    run_replay,
)
from wildfireops.sources.base import SourceAdapter, SourceBatch


class _Adapter:
    def __init__(self, source_name: str) -> None:
        self._source_name = source_name

    @property
    def source_name(self) -> str:
        return self._source_name

    async def fetch(self) -> SourceBatch:
        raise AssertionError("the fake service owns this test")


class _FakeService:
    def __init__(self, outcomes: dict[str, str]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    async def run_source(self, adapter: SourceAdapter) -> IngestionRun:
        self.calls.append(adapter.source_name)
        outcome = self.outcomes[adapter.source_name]
        return IngestionRun(
            source_name=adapter.source_name,
            accepted=2 if outcome == "success" else 0,
            deduplicated=1 if outcome == "success" else 0,
            quarantined=0,
            outcome=outcome,
        )


class _CapturingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def info(self, event: str, **values: object) -> None:
        self.events.append((event, values))


def _next(values: tuple[float, ...]) -> Iterator[float]:
    return iter(values)


def test_blank_firms_key_is_treated_as_unconfigured() -> None:
    assert Settings(firms_map_key="").firms_map_key is None  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("firms_day_range", 0),
        ("firms_day_range", -1),
        ("firms_day_range", 6),
        ("firms_day_range", True),
        ("clustering_spatial_radius_meters", 0),
        ("clustering_spatial_radius_meters", float("inf")),
        ("clustering_spatial_radius_meters", True),
        ("clustering_temporal_window_seconds", 0),
        ("clustering_temporal_window_seconds", float("nan")),
        ("clustering_temporal_window_seconds", False),
        ("clustering_minimum_points", 0),
        ("clustering_minimum_points", True),
        ("clustering_algorithm_version", "   "),
    ),
)
def test_worker_settings_reject_invalid_numeric_configuration(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_run_once_continues_after_partial_failure_and_logs_each_run() -> None:
    service = _FakeService({"nasa_firms": "failed", "nws": "success"})
    logger = _CapturingLogger()
    times = _next((10.0, 10.125, 20.0, 20.25))
    job_ids = iter(("job-firms", "job-nws"))
    sources = (
        ScheduledSource(_Adapter("nasa_firms"), interval_seconds=60.0),
        ScheduledSource(_Adapter("nws"), interval_seconds=120.0),
    )

    exit_code = await run_once(
        service,
        sources,
        logger=logger,
        monotonic=lambda: next(times),
        job_id_factory=lambda: next(job_ids),
    )

    assert exit_code == 0
    assert service.calls == ["nasa_firms", "nws"]
    assert logger.events == [
        (
            "ingestion_run",
            {
                "job_id": "job-firms",
                "source_name": "nasa_firms",
                "accepted": 0,
                "deduplicated": 0,
                "quarantined": 0,
                "duration_ms": 125,
                "outcome": "failed",
            },
        ),
        (
            "ingestion_run",
            {
                "job_id": "job-nws",
                "source_name": "nws",
                "accepted": 2,
                "deduplicated": 1,
                "quarantined": 0,
                "duration_ms": 250,
                "outcome": "success",
            },
        ),
    ]
    serialized_events = repr(logger.events)
    assert "raw_payload" not in serialized_events
    assert "firms_map_key" not in serialized_events
    assert "database_url" not in serialized_events


@pytest.mark.asyncio
async def test_run_once_exits_nonzero_only_when_every_source_fails() -> None:
    logger = _CapturingLogger()
    service = _FakeService({"nasa_firms": "failed", "nws": "failed"})
    sources = (
        ScheduledSource(_Adapter("nasa_firms"), interval_seconds=60.0),
        ScheduledSource(_Adapter("nws"), interval_seconds=120.0),
    )

    exit_code = await run_once(service, sources, logger=logger)

    assert exit_code == 1
    assert len(logger.events) == 2


@pytest.mark.asyncio
async def test_build_live_adapters_uses_settings_and_skips_unconfigured_firms() -> None:
    settings = Settings(
        firms_map_key=None,
        firms_area_url="https://firms.example.invalid/area/csv",
        firms_bbox="-122.40,39.20,-120.30,41.00",
        firms_source="VIIRS_SNPP_NRT",
        firms_day_range=1,
        firms_poll_interval_seconds=60.0,
        nws_observation_url="https://weather.example.invalid/latest",
        nws_poll_interval_seconds=120.0,
    )

    async with httpx.AsyncClient() as client:
        configured = build_live_adapters(settings, client)

    assert [source.adapter.source_name for source in configured] == ["nws"]
    assert [source.interval_seconds for source in configured] == [120.0]


@pytest.mark.asyncio
async def test_build_live_adapters_includes_configured_sources() -> None:
    settings = Settings(
        firms_map_key=SecretStr("test-map-key"),
        firms_area_url="https://firms.example.invalid/area/csv",
        firms_bbox="-122.40,39.20,-120.30,41.00",
        firms_source="VIIRS_SNPP_NRT",
        firms_day_range=1,
        firms_poll_interval_seconds=60.0,
        nws_observation_url="https://weather.example.invalid/latest",
        nws_poll_interval_seconds=120.0,
    )
    async with httpx.AsyncClient() as client:
        configured = build_live_adapters(settings, client)

    assert [source.adapter.source_name for source in configured] == [
        "nasa_firms",
        "nws",
    ]
    assert [source.interval_seconds for source in configured] == [60.0, 120.0]
    assert "test-map-key" not in repr(configured)


@pytest.mark.asyncio
async def test_replay_is_offline_and_does_not_build_live_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = Path("tests/fixtures/replay-small")
    logger = _CapturingLogger()

    class ReplayService:
        source_name: str | None = None
        batch: SourceBatch | None = None

        async def run_source(self, adapter: object) -> IngestionRun:
            source_name = getattr(adapter, "source_name")
            batch = await getattr(adapter, "fetch")()
            self.source_name = source_name
            self.batch = batch
            return IngestionRun(
                source_name=source_name,
                accepted=len(batch.observations),
                deduplicated=0,
                quarantined=0,
                outcome="success",
            )

    service = ReplayService()

    def fail_live_construction(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("replay must not construct live adapters")

    monkeypatch.setattr(
        "wildfireops.ingestion.worker.build_live_adapters",
        fail_live_construction,
    )

    exit_code = await run_replay(package, service, logger=logger)

    assert exit_code == 0
    assert service.source_name == "replay:replay-small-v1"
    assert service.batch is not None
    assert [item.identity for item in service.batch.observations] == [
        "nasa_firms:detection-1812",
        "nasa_firms:detection-1818",
    ]
    assert len(logger.events) == 1
