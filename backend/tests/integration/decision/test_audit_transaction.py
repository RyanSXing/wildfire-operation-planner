from datetime import UTC, datetime
from uuid import UUID

import pytest
from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.decision.commands import (
    DecisionCommandService,
    DecisionRecommendation,
    DecisionRequest,
)
from wildfireops.persistence.decision_models import (
    AuditEventModel,
    DecisionActionModel,
    DecisionAssignmentModel,
    IdempotencyKeyModel,
    IncidentSnapshotModel,
    RecommendationAssignmentModel,
    RecommendationModel,
    ScenarioModel,
    ScenarioVersionModel,
)
from wildfireops.persistence.decisions import DecisionRepository
from wildfireops.persistence.observed_models import (
    ExposedAssetModel,
    ResourceUnitModel,
    WildfireIncidentModel,
)


_REFERENCE = datetime(2024, 7, 24, 18, 30, tzinfo=UTC)


class _CurrentDecisionRepository(DecisionRepository):
    async def current_input_version(
        self,
        recommendation: DecisionRecommendation,
    ) -> str:
        return recommendation.input_version


@pytest.mark.asyncio
async def test_assignment_audit_failure_rolls_back_and_same_key_retries(
    db_session: AsyncSession,
) -> None:
    recommendation_id = str(await _seed_recommendation(db_session))

    async def fail_after_assignments() -> None:
        raise RuntimeError("injected audit failure")

    assert db_session.bind is not None
    with pytest.raises(RuntimeError, match="injected audit failure"):
        async with AsyncSession(
            bind=db_session.bind,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            async with session.begin():
                service = DecisionCommandService(
                    _CurrentDecisionRepository(
                        session,
                        after_assignment_insert=fail_after_assignments,
                    )
                )
                await service.decide(
                    recommendation_id,
                    DecisionRequest("approve", "Dispatch"),
                    "demo-operator",
                    "retryable-decision",
                )

    assert await _count(db_session, DecisionActionModel) == 0
    assert await _count(db_session, DecisionAssignmentModel) == 0
    assert await _count(db_session, AuditEventModel) == 0
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(IdempotencyKeyModel)
            .where(IdempotencyKeyModel.key == "retryable-decision")
        )
        == 0
    )

    async with AsyncSession(
        bind=db_session.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as session:
        async with session.begin():
            stored = await DecisionCommandService(
                _CurrentDecisionRepository(session)
            ).decide(
                recommendation_id,
                DecisionRequest("approve", "Dispatch"),
                "demo-operator",
                "retryable-decision",
            )

    assert stored.recommendation_id == UUID(recommendation_id)
    assert await _count(db_session, DecisionActionModel) == 1
    assert await _count(db_session, DecisionAssignmentModel) == 1
    assert await _count(db_session, AuditEventModel) == 1
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(IdempotencyKeyModel)
            .where(IdempotencyKeyModel.key == "retryable-decision")
        )
        == 1
    )


async def _count(session: AsyncSession, model: type[object]) -> int:
    value = await session.scalar(select(func.count()).select_from(model))
    assert value is not None
    return value


async def _seed_recommendation(session: AsyncSession) -> UUID:
    incident = WildfireIncidentModel(
        geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
        first_observed_at=_REFERENCE,
        last_observed_at=_REFERENCE,
    )
    resource = ResourceUnitModel(
        resource_id="engine-transaction",
        resource_type="engine",
        capabilities=["water"],
        capacity=2,
        available=True,
        status="available",
        geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
        raw_metadata={},
    )
    asset = ExposedAssetModel(
        asset_id="town-transaction",
        asset_kind="community",
        name="Transaction Town",
        population=10,
        geometry=WKTElement("POINT(-121.7 39.9)", srid=4326),
        raw_metadata={},
    )
    session.add_all([incident, resource, asset])
    await session.flush()
    snapshot = IncidentSnapshotModel(
        incident_id=incident.id,
        snapshot_version=1,
        source_versions={},
        incident_state={},
        asset_state=[],
        resource_state=[],
        captured_at=_REFERENCE,
    )
    session.add(snapshot)
    await session.flush()
    scenario = ScenarioModel(
        incident_id=incident.id,
        objective="Test rollback",
        author_id="demo-operator",
        algorithm_config_version="scenario-v1",
    )
    session.add(scenario)
    await session.flush()
    version = ScenarioVersionModel(
        scenario_id=scenario.id,
        incident_id=incident.id,
        version=1,
        incident_snapshot_id=snapshot.id,
        graph_version="graph-v1",
        created_by="demo-operator",
    )
    session.add(version)
    await session.flush()
    recommendation = RecommendationModel(
        scenario_version_id=version.id,
        input_version="a" * 64,
        source_versions={},
        graph_version="graph-v1",
        risk_version="risk-v1",
        algorithm_version="allocation-v1",
        solver_status="OPTIMAL",
        runtime_milliseconds=1,
        request_inputs={},
        objective_components={
            "travel_cost": 5,
            "uncovered_risk_penalty": 0,
            "objective_value": 5,
        },
        uncovered_destination_ids=[],
        explanation={},
    )
    session.add(recommendation)
    await session.flush()
    session.add(
        RecommendationAssignmentModel(
            recommendation_id=recommendation.id,
            resource_id=resource.resource_id,
            destination_id=asset.asset_id,
            route={
                "status": "reachable",
                "edge_ids": ["edge-1"],
                "distance_meters": 1_000.0,
                "travel_minutes": 5.0,
                "graph_version": "graph-v1",
                "closure_hash": "b" * 64,
            },
            travel_minutes=5.0,
            capacity=2,
        )
    )
    await session.flush()
    return recommendation.id
