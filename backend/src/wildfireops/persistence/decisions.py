from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.decision.commands import (
    AuditEvent,
    DecisionRecommendation,
    StoredDecision,
    ValidatedDecision,
)
from wildfireops.decision.recommendations import StoredRecommendationAssignment
from wildfireops.decision.recommendations import recommendation_input_version
from wildfireops.domain.scenario_versions import IdempotencyClaim
from wildfireops.persistence.decision_models import (
    AuditEventModel,
    DecisionActionModel,
    DecisionAssignmentModel,
    RecommendationAssignmentModel,
    RecommendationModel,
    ScenarioVersionModel,
)
from wildfireops.persistence.scenarios import ScenarioRepository
from wildfireops.persistence.incidents import acquire_incident_refresh_lock
from wildfireops.persistence.observed_models import ResourceUnitModel
from wildfireops.persistence.recommendations import RecommendationRepository


class DecisionRepository:
    """Session-bound adapter; the application owns its transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        after_assignment_insert: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._session = session
        self._idempotency = ScenarioRepository(session)
        self._after_assignment_insert = after_assignment_insert

    async def claim_idempotency(
        self,
        *,
        scope: str,
        key: str,
        request_hash: str,
    ) -> IdempotencyClaim:
        return await self._idempotency.claim_idempotency(
            scope=scope,
            key=key,
            request_hash=request_hash,
        )

    async def complete_idempotency(
        self,
        *,
        claim_id: UUID,
        response_type: str,
        response_id: UUID,
    ) -> None:
        await self._idempotency.complete_idempotency(
            claim_id=claim_id,
            response_type=response_type,
            response_id=response_id,
        )

    async def lock_recommendation(
        self,
        recommendation_id: UUID,
    ) -> DecisionRecommendation | None:
        model = await self._session.scalar(
            select(RecommendationModel)
            .where(RecommendationModel.id == recommendation_id)
            .with_for_update()
        )
        if model is None:
            return None
        version = await self._session.get(
            ScenarioVersionModel,
            model.scenario_version_id,
        )
        if version is None:
            raise RuntimeError("recommendation scenario version does not exist")
        proposals = (
            await self._session.scalars(
                select(RecommendationAssignmentModel)
                .where(RecommendationAssignmentModel.recommendation_id == model.id)
                .order_by(
                    RecommendationAssignmentModel.resource_id,
                    RecommendationAssignmentModel.destination_id,
                )
            )
        ).all()
        terminal_decision_id = await self._session.scalar(
            select(DecisionActionModel.id).where(
                DecisionActionModel.recommendation_id == model.id
            )
        )
        return DecisionRecommendation(
            id=model.id,
            scenario_version_id=model.scenario_version_id,
            incident_snapshot_id=version.incident_snapshot_id,
            input_version=model.input_version,
            source_versions=model.source_versions,
            graph_version=model.graph_version,
            risk_version=model.risk_version,
            algorithm_version=model.algorithm_version,
            solver_status=model.solver_status,
            request_inputs=model.request_inputs,
            proposals=tuple(
                StoredRecommendationAssignment(
                    resource_id=row.resource_id,
                    destination_id=row.destination_id,
                    route=row.route,
                    travel_minutes=row.travel_minutes,
                    capacity=row.capacity,
                )
                for row in proposals
            ),
            terminal_decision_id=terminal_decision_id,
        )

    async def acquire_incident_refresh_lock(self) -> None:
        await acquire_incident_refresh_lock(self._session)

    async def current_input_version(
        self,
        recommendation: DecisionRecommendation,
        *,
        risk_version: str,
        allocation_version: str,
    ) -> str | None:
        context = await RecommendationRepository(self._session).load_context(
            recommendation.scenario_version_id
        )
        if (
            context is None
            or context.scenario_version != context.latest_scenario_version
            or context.snapshot_version != context.latest_snapshot_version
            or context.snapshot_id != recommendation.incident_snapshot_id
        ):
            return None
        return recommendation_input_version(
            context,
            risk_version=risk_version,
            allocation_version=allocation_version,
        )

    async def lock_resources(
        self,
        resource_ids: tuple[str, ...],
    ) -> frozenset[str]:
        locked = tuple(
            await self._session.scalars(
                select(ResourceUnitModel.resource_id)
                .where(ResourceUnitModel.resource_id.in_(resource_ids))
                .order_by(ResourceUnitModel.resource_id)
                .with_for_update()
            )
        )
        if set(locked) != set(resource_ids):
            raise RuntimeError("selected live resource does not exist")
        conflicts = tuple(
            await self._session.scalars(
                select(DecisionAssignmentModel.resource_id).where(
                    DecisionAssignmentModel.resource_id.in_(resource_ids),
                    DecisionAssignmentModel.status == "active",
                )
            )
        )
        return frozenset(conflicts)

    async def store_decision(
        self,
        validated: ValidatedDecision,
        actor_id: str,
        idempotency_key_id: UUID,
    ) -> UUID:
        model = DecisionActionModel(
            recommendation_id=validated.recommendation.id,
            idempotency_key_id=idempotency_key_id,
            action=validated.action,
            note=validated.note,
            actor_id=actor_id,
            edited_assignments=(
                []
                if validated.action != "edit"
                else [
                    {
                        "resource_id": item.resource_id,
                        "destination_id": item.destination_id,
                    }
                    for item in validated.assignments
                ]
            ),
        )
        self._session.add(model)
        await self._session.flush()
        return model.id

    async def store_assignments_if_approved(
        self,
        validated: ValidatedDecision,
        decision_id: UUID,
    ) -> None:
        if validated.action == "reject":
            return
        self._session.add_all(
            [
                DecisionAssignmentModel(
                    decision_action_id=decision_id,
                    resource_id=item.resource_id,
                    destination_id=item.destination_id,
                    route=dict(item.route),
                    travel_minutes=item.travel_minutes,
                    capacity=item.capacity,
                )
                for item in validated.assignments
            ]
        )
        await self._session.flush()
        if self._after_assignment_insert is not None:
            await self._after_assignment_insert()

    async def append_audit_event(
        self,
        validated: ValidatedDecision,
        actor_id: str,
        decision_id: UUID,
    ) -> None:
        proposed_pairs = [
            {
                "resource_id": item.resource_id,
                "destination_id": item.destination_id,
            }
            for item in validated.recommendation.proposals
        ]
        final_pairs = [
            {
                "resource_id": item.resource_id,
                "destination_id": item.destination_id,
            }
            for item in validated.assignments
        ]
        recommendation = validated.recommendation
        self._session.add(
            AuditEventModel(
                decision_action_id=decision_id,
                actor_id=actor_id,
                event_type={
                    "approve": "recommendation.approved",
                    "reject": "recommendation.rejected",
                    "edit": "recommendation.edited",
                }[validated.action],
                aggregate_type="recommendation",
                aggregate_id=recommendation.id,
                before_state={
                    "recommendation_id": str(recommendation.id),
                    "status": "proposed",
                    "proposed_pairs": proposed_pairs,
                },
                after_state={
                    "decision_id": str(decision_id),
                    "action": validated.action,
                    "note": validated.note,
                    "final_pairs": final_pairs,
                },
                inputs={
                    "scenario_version_id": str(recommendation.scenario_version_id),
                    "incident_snapshot_id": str(recommendation.incident_snapshot_id),
                    "staleness_token": recommendation.input_version,
                    "source_versions": dict(recommendation.source_versions),
                    "algorithm_versions": {
                        "graph": recommendation.graph_version,
                        "risk": recommendation.risk_version,
                        "allocation": recommendation.algorithm_version,
                    },
                },
            )
        )
        await self._session.flush()

    async def get_decision(self, decision_id: UUID) -> StoredDecision | None:
        model = await self._session.get(DecisionActionModel, decision_id)
        if model is None:
            return None
        rows = (
            await self._session.scalars(
                select(DecisionAssignmentModel)
                .where(DecisionAssignmentModel.decision_action_id == model.id)
                .order_by(
                    DecisionAssignmentModel.resource_id,
                    DecisionAssignmentModel.destination_id,
                )
            )
        ).all()
        return StoredDecision(
            id=model.id,
            recommendation_id=model.recommendation_id,
            action=model.action,
            note=model.note,
            actor_id=model.actor_id,
            assignments=tuple(
                StoredRecommendationAssignment(
                    resource_id=row.resource_id,
                    destination_id=row.destination_id,
                    route=row.route,
                    travel_minutes=row.travel_minutes,
                    capacity=row.capacity,
                )
                for row in rows
            ),
            created_at=model.created_at,
        )


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_events(
        self,
        recommendation_id: UUID | None,
    ) -> tuple[AuditEvent, ...]:
        statement = select(AuditEventModel)
        if recommendation_id is not None:
            statement = statement.where(
                AuditEventModel.aggregate_type == "recommendation",
                AuditEventModel.aggregate_id == recommendation_id,
            )
        rows = (
            await self._session.scalars(
                statement.order_by(
                    AuditEventModel.occurred_at.desc(),
                    AuditEventModel.id.desc(),
                )
            )
        ).all()
        return tuple(_audit_event(row) for row in rows)

    async def get_event(self, event_id: UUID) -> AuditEvent | None:
        model = await self._session.get(AuditEventModel, event_id)
        return None if model is None else _audit_event(model)


def _audit_event(model: AuditEventModel) -> AuditEvent:
    if (
        model.decision_action_id is None
        or model.before_state is None
        or model.after_state is None
    ):
        raise RuntimeError("decision audit event is incomplete")
    return AuditEvent(
        id=model.id,
        decision_action_id=model.decision_action_id,
        actor_id=model.actor_id,
        event_type=model.event_type,
        aggregate_type=model.aggregate_type,
        aggregate_id=model.aggregate_id,
        before_state=model.before_state,
        after_state=model.after_state,
        inputs=model.inputs,
        occurred_at=model.occurred_at,
    )
