from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.api.schemas.incidents import Freshness
from wildfireops.api.schemas.sources import SourceStatusResponse
from wildfireops.config import Settings
from wildfireops.persistence.observed_models import SourceStatusModel


type UtcClock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class _SourcePolicy:
    poll_interval_seconds: float
    stale_after_seconds: float


class SourceQueryService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        clock: UtcClock,
    ) -> None:
        self._session = session
        self._settings = settings
        self._clock = clock

    async def list_statuses(self) -> tuple[SourceStatusResponse, ...]:
        rows = (
            await self._session.scalars(
                select(SourceStatusModel).order_by(SourceStatusModel.source_name)
            )
        ).all()
        reference_at = _utc(self._clock(), "API clock")
        return tuple(self._status(row, reference_at) for row in rows)

    def _status(
        self,
        row: SourceStatusModel,
        reference_at: datetime,
    ) -> SourceStatusResponse:
        policy = _source_policy(row.source_name, self._settings)
        attempted_at = _utc(row.last_attempted_at, "source last attempt")
        last_success_at = (
            None
            if row.last_success_at is None
            else _utc(row.last_success_at, "source last success")
        )
        return SourceStatusResponse(
            source_name=row.source_name,
            last_attempted_at=attempted_at,
            last_success_at=last_success_at,
            next_retry_at=(
                None
                if policy is None
                else attempted_at
                + timedelta(seconds=policy.poll_interval_seconds)
            ),
            freshness=_source_freshness(
                outcome=row.outcome,
                last_success_at=last_success_at,
                reference_at=reference_at,
                policy=policy,
            ),
            accepted_count=row.accepted_count,
            deduplicated_count=row.deduplicated_count,
            quarantined_count=row.quarantined_count,
            last_error_code=_safe_error_code(row.error_message),
        )


def _source_policy(source_name: str, settings: Settings) -> _SourcePolicy | None:
    normalized = source_name.strip().lower()
    if normalized in {"nasa_firms", "firms"}:
        return _SourcePolicy(
            poll_interval_seconds=settings.firms_poll_interval_seconds,
            stale_after_seconds=settings.risk_fire_freshness_seconds,
        )
    if normalized in {"nws", "noaa", "noaa_nws"}:
        return _SourcePolicy(
            poll_interval_seconds=settings.nws_poll_interval_seconds,
            stale_after_seconds=settings.risk_weather_freshness_seconds,
        )
    return None


def _source_freshness(
    *,
    outcome: str,
    last_success_at: datetime | None,
    reference_at: datetime,
    policy: _SourcePolicy | None,
) -> Freshness:
    if last_success_at is None or policy is None:
        return "unavailable"
    if outcome != "success":
        return "stale"
    age_seconds = (reference_at - last_success_at).total_seconds()
    return "fresh" if age_seconds <= policy.stale_after_seconds else "stale"


def _safe_error_code(error_message: str | None) -> str | None:
    if error_message is None:
        return None
    normalized = error_message.casefold()
    if "unavailable" in normalized:
        return "source_unavailable"
    if "timeout" in normalized or "timed out" in normalized:
        return "source_timeout"
    if "validation" in normalized or "invalid" in normalized:
        return "source_validation_error"
    return "source_processing_error"


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError(f"stored {field} must be UTC")
    return value
