from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.domain.observations import NormalizedObservation, WeatherObservation
from wildfireops.persistence.observations import IngestStats, ObservationRepository
from wildfireops.persistence.observed_models import SourceObservationModel


@pytest.mark.asyncio
async def test_upsert_many_is_idempotent_by_source_identity(
    db_session: AsyncSession,
) -> None:
    first = NormalizedObservation(
        source_name="nasa_firms",
        source_record_id="viirs-42",
        observed_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
        longitude=-121.6,
        latitude=39.8,
        confidence=0.9,
        intensity=18.4,
        raw_payload={
            "satellites": ("NOAA-20",),
            "metadata": {"quality_checked": True},
        },
    )
    duplicate = NormalizedObservation(
        source_name="nasa_firms",
        source_record_id="viirs-42",
        observed_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
        longitude=-121.6,
        latitude=39.8,
        confidence=0.9,
        intensity=18.4,
        raw_payload={
            "satellites": ("NOAA-20",),
            "metadata": {"quality_checked": True},
        },
    )
    repository = ObservationRepository()

    first_stats = await repository.upsert_many(db_session, [first, duplicate])
    second_stats = await repository.upsert_many(db_session, [first, duplicate])

    assert first_stats == IngestStats(inserted=1, deduplicated=1)
    assert second_stats == IngestStats(inserted=0, deduplicated=2)
    row_count = await db_session.scalar(
        select(func.count()).select_from(SourceObservationModel)
    )
    assert row_count == 1


def test_from_domain_uses_explicit_type_and_materializes_json() -> None:
    observed_at = datetime(2024, 7, 24, 18, tzinfo=UTC)
    fire = NormalizedObservation(
        source_name="nasa_firms",
        source_record_id="viirs-no-intensity",
        observed_at=observed_at,
        longitude=-121.6,
        latitude=39.8,
        confidence=0.9,
        intensity=None,
        raw_payload={"nested": ({"value": 1},)},
    )
    weather = WeatherObservation(
        source_name="nws",
        source_record_id="weather-no-temperature",
        observed_at=observed_at,
        longitude=-121.6,
        latitude=39.8,
        wind_speed_mps=5.0,
        wind_direction_degrees=270.0,
        temperature_celsius=None,
        raw_payload={"nested": ({"value": 1},)},
    )

    fire_values = SourceObservationModel.from_domain(fire)
    weather_values = SourceObservationModel.from_domain(weather)

    assert fire_values["observation_kind"] == "fire"
    assert weather_values["observation_kind"] == "weather"
    raw_payload = fire_values["raw_payload"]
    assert raw_payload == {"nested": [{"value": 1}]}
    assert type(raw_payload) is dict
    assert isinstance(raw_payload, dict)
    assert type(raw_payload["nested"]) is list


@pytest.mark.asyncio
async def test_upsert_many_leaves_transaction_ownership_to_caller(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = NormalizedObservation(
        source_name="nasa_firms",
        source_record_id="viirs-transaction-guard",
        observed_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
        longitude=-121.6,
        latitude=39.8,
        confidence=0.9,
        intensity=18.4,
        raw_payload={"satellite": "NOAA-20"},
    )
    commit_spy = AsyncMock(side_effect=AssertionError("repository must not commit"))
    rollback_spy = AsyncMock(
        side_effect=AssertionError("repository must not roll back")
    )
    monkeypatch.setattr(db_session, "commit", commit_spy)
    monkeypatch.setattr(db_session, "rollback", rollback_spy)

    result = await ObservationRepository().upsert_many(db_session, [record])

    assert result == IngestStats(inserted=1, deduplicated=0)
    assert db_session.in_transaction()
    commit_spy.assert_not_awaited()
    rollback_spy.assert_not_awaited()
