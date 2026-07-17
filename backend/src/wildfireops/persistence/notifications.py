import json
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.persistence.decision_models import IncidentSnapshotModel


EVENT_CHANNEL = "wildfireops_events"


async def notify_ingestion_success(
    session: AsyncSession,
    *,
    snapshot_ids: tuple[UUID, ...],
    source_name: str,
) -> None:
    unique_snapshot_ids = set(snapshot_ids)
    incident_ids: set[UUID] = set()
    if unique_snapshot_ids:
        rows = (
            await session.execute(
                select(
                    IncidentSnapshotModel.id, IncidentSnapshotModel.incident_id
                ).where(IncidentSnapshotModel.id.in_(unique_snapshot_ids))
            )
        ).all()
        resolved_snapshot_ids = {snapshot_id for snapshot_id, _ in rows}
        if resolved_snapshot_ids != unique_snapshot_ids:
            raise ValueError("snapshot IDs must identify persisted incident snapshots")
        incident_ids = {incident_id for _, incident_id in rows}

    for incident_id in sorted(incident_ids, key=str):
        await _notify(
            session,
            name="incident-updated",
            data={"incidentId": str(incident_id)},
        )
    await notify_source_status(session, source_name=source_name)


async def notify_source_status(
    session: AsyncSession,
    *,
    source_name: str,
) -> None:
    if not source_name.strip():
        raise ValueError("source name must not be empty")
    await _notify(
        session,
        name="source-status-updated",
        data={"sourceName": source_name},
    )


async def _notify(
    session: AsyncSession,
    *,
    name: str,
    data: dict[str, str],
) -> None:
    payload = json.dumps(
        {"data": data, "name": name},
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    await session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": EVENT_CHANNEL, "payload": payload},
    )
