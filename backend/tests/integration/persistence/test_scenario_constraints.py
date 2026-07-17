from datetime import UTC, datetime

import pytest
from geoalchemy2.elements import WKTElement
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.persistence.decision_models import (
    IncidentSnapshotModel,
    ScenarioModel,
    ScenarioVersionModel,
)
from wildfireops.persistence.observed_models import WildfireIncidentModel


@pytest.mark.asyncio
async def test_scenario_version_requires_snapshot_from_same_incident(
    db_session: AsyncSession,
) -> None:
    observed_at = datetime(2024, 7, 24, 18, tzinfo=UTC)
    first_incident = WildfireIncidentModel(
        geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
        first_observed_at=observed_at,
        last_observed_at=observed_at,
    )
    second_incident = WildfireIncidentModel(
        geometry=WKTElement("POINT(-120.6 38.8)", srid=4326),
        first_observed_at=observed_at,
        last_observed_at=observed_at,
    )
    db_session.add_all([first_incident, second_incident])
    await db_session.flush()

    first_snapshot = IncidentSnapshotModel(
        incident_id=first_incident.id,
        snapshot_version=1,
        incident_state={"status": "active"},
    )
    second_snapshot = IncidentSnapshotModel(
        incident_id=second_incident.id,
        snapshot_version=1,
        incident_state={"status": "active"},
    )
    scenario = ScenarioModel(
        incident_id=first_incident.id,
        objective="Protect exposed communities",
        author_id="demo-operator",
        algorithm_config_version="scenario-v1",
    )
    db_session.add_all([first_snapshot, second_snapshot, scenario])
    await db_session.flush()

    matching_version = ScenarioVersionModel(
        scenario_id=scenario.id,
        incident_id=first_incident.id,
        version=1,
        incident_snapshot_id=first_snapshot.id,
        created_by="demo-operator",
    )
    db_session.add(matching_version)
    await db_session.flush()

    cross_incident_version = ScenarioVersionModel(
        scenario_id=scenario.id,
        incident_id=first_incident.id,
        version=2,
        incident_snapshot_id=second_snapshot.id,
        created_by="demo-operator",
    )
    db_session.add(cross_incident_version)

    with pytest.raises(
        IntegrityError,
        match="fk_scenario_versions_snapshot_incident",
    ):
        await db_session.flush()
