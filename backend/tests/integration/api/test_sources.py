from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wildfireops.main import create_app
from wildfireops.persistence.observed_models import SourceStatusModel


_REFERENCE = datetime(2024, 7, 24, 18, 30, tzinfo=UTC)


def _test_app(db_session: AsyncSession) -> FastAPI:
    app = create_app()
    assert db_session.bind is not None
    app.state.session_factory = async_sessionmaker(
        bind=db_session.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    app.state.clock = lambda: _REFERENCE
    return app


@pytest.mark.asyncio
async def test_source_status_reports_retry_freshness_counts_and_safe_error_codes(
    db_session: AsyncSession,
) -> None:
    db_session.add_all(
        [
            SourceStatusModel(
                source_name="firms",
                outcome="failed",
                last_attempted_at=_REFERENCE - timedelta(minutes=1),
                last_success_at=None,
                accepted_count=0,
                deduplicated_count=0,
                quarantined_count=0,
                error_message="TimeoutError",
            ),
            SourceStatusModel(
                source_name="nasa_firms",
                outcome="success",
                last_attempted_at=_REFERENCE - timedelta(minutes=5),
                last_success_at=_REFERENCE - timedelta(minutes=5),
                accepted_count=8,
                deduplicated_count=2,
                quarantined_count=1,
                error_message=None,
            ),
            SourceStatusModel(
                source_name="nws",
                outcome="failed",
                last_attempted_at=_REFERENCE - timedelta(minutes=2),
                last_success_at=_REFERENCE - timedelta(minutes=5),
                accepted_count=0,
                deduplicated_count=0,
                quarantined_count=0,
                error_message=(
                    "nws unavailable at https://api.weather.gov?token=secret-value"
                ),
            ),
            SourceStatusModel(
                source_name="replay_archive",
                outcome="success",
                last_attempted_at=_REFERENCE,
                last_success_at=_REFERENCE,
                accepted_count=20,
                deduplicated_count=0,
                quarantined_count=0,
                error_message=None,
            ),
        ]
    )
    await db_session.flush()

    app = _test_app(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/sources/status")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "sourceName": "firms",
                "lastAttemptedAt": "2024-07-24T18:29:00Z",
                "lastSuccessAt": None,
                "nextRetryAt": "2024-07-24T18:34:00Z",
                "freshness": "unavailable",
                "acceptedCount": 0,
                "deduplicatedCount": 0,
                "quarantinedCount": 0,
                "lastErrorCode": "source_timeout",
            },
            {
                "sourceName": "nasa_firms",
                "lastAttemptedAt": "2024-07-24T18:25:00Z",
                "lastSuccessAt": "2024-07-24T18:25:00Z",
                "nextRetryAt": "2024-07-24T18:30:00Z",
                "freshness": "fresh",
                "acceptedCount": 8,
                "deduplicatedCount": 2,
                "quarantinedCount": 1,
                "lastErrorCode": None,
            },
            {
                "sourceName": "nws",
                "lastAttemptedAt": "2024-07-24T18:28:00Z",
                "lastSuccessAt": "2024-07-24T18:25:00Z",
                "nextRetryAt": "2024-07-24T18:33:00Z",
                "freshness": "stale",
                "acceptedCount": 0,
                "deduplicatedCount": 0,
                "quarantinedCount": 0,
                "lastErrorCode": "source_unavailable",
            },
            {
                "sourceName": "replay_archive",
                "lastAttemptedAt": "2024-07-24T18:30:00Z",
                "lastSuccessAt": "2024-07-24T18:30:00Z",
                "nextRetryAt": None,
                "freshness": "unavailable",
                "acceptedCount": 20,
                "deduplicatedCount": 0,
                "quarantinedCount": 0,
                "lastErrorCode": None,
            },
        ]
    }
    assert "secret-value" not in response.text
    assert "api.weather.gov" not in response.text


@pytest.mark.asyncio
async def test_source_status_uses_weather_policy_for_replay_noaa_ncei(
    db_session: AsyncSession,
) -> None:
    observed_at = _REFERENCE - timedelta(minutes=30)
    db_session.add(
        SourceStatusModel(
            source_name="noaa_ncei",
            outcome="success",
            last_attempted_at=observed_at,
            last_success_at=observed_at,
            accepted_count=1,
            deduplicated_count=0,
            quarantined_count=0,
            error_message=None,
        )
    )
    await db_session.flush()

    app = _test_app(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/sources/status")

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "sourceName": "noaa_ncei",
            "lastAttemptedAt": "2024-07-24T18:00:00Z",
            "lastSuccessAt": "2024-07-24T18:00:00Z",
            "nextRetryAt": "2024-07-24T18:05:00Z",
            "freshness": "fresh",
            "acceptedCount": 1,
            "deduplicatedCount": 0,
            "quarantinedCount": 0,
            "lastErrorCode": None,
        }
    ]
