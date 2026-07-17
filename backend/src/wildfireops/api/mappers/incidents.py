from collections.abc import Mapping
from typing import cast

from pydantic import JsonValue

from wildfireops.api.schemas.incidents import (
    DetailedRiskResponse,
    DetectionResponse,
    ExposedAssetResponse,
    IncidentDetailResponse,
    IncidentSummaryResponse,
    RiskContributionResponse,
    RiskResponse,
    SimulatedResourceResponse,
    TimelineFrameResponse,
)
from wildfireops.application.read_models import (
    DetailedRiskReadModel,
    DetectionReadModel,
    ExposedAssetReadModel,
    IncidentDetailReadModel,
    IncidentSummaryReadModel,
    RiskReadModel,
    SimulatedResourceReadModel,
    TimelineFrameReadModel,
)
from wildfireops.domain.observations import FrozenJsonObject, FrozenJsonValue


def incident_summary(model: IncidentSummaryReadModel) -> IncidentSummaryResponse:
    return IncidentSummaryResponse(
        id=model.id,
        name=model.name,
        risk=_risk(model.risk),
        exposed_asset_count=model.exposed_asset_count,
        last_observed_at=model.last_observed_at,
        freshness=model.freshness,
    )


def incident_detail(model: IncidentDetailReadModel) -> IncidentDetailResponse:
    return IncidentDetailResponse(
        id=model.id,
        name=model.name,
        status=model.status,
        snapshot_id=model.snapshot_id,
        snapshot_version=model.snapshot_version,
        geometry=_object(model.geometry),
        first_observed_at=model.first_observed_at,
        last_observed_at=model.last_observed_at,
        freshness=model.freshness,
        risk=_detailed_risk(model.risk),
        detections=tuple(_detection(item) for item in model.detections),
        exposed_assets=tuple(_asset(item) for item in model.exposed_assets),
        simulated_resources=tuple(
            _resource(item) for item in model.simulated_resources
        ),
        source_versions=_object(model.source_versions),
    )


def timeline_frame(model: TimelineFrameReadModel) -> TimelineFrameResponse:
    return TimelineFrameResponse(
        snapshot_id=model.snapshot_id,
        snapshot_version=model.snapshot_version,
        captured_at=model.captured_at,
        reference_at=model.reference_at,
        last_observed_at=model.last_observed_at,
        geometry=_object(model.geometry),
        risk=_risk(model.risk),
        detections=tuple(_detection(item) for item in model.detections),
        exposed_asset_count=model.exposed_asset_count,
        freshness=model.freshness,
    )


def _risk(model: RiskReadModel) -> RiskResponse:
    return RiskResponse(
        score=model.score,
        algorithm_version=model.algorithm_version,
        contributions=tuple(
            RiskContributionResponse(
                name=item.name,
                raw_value=_json(item.raw_value),
                normalized_value=item.normalized_value,
                weight=item.weight,
                contribution=item.contribution,
            )
            for item in model.contributions
        ),
    )


def _detailed_risk(model: DetailedRiskReadModel) -> DetailedRiskResponse:
    summary = _risk(model)
    return DetailedRiskResponse(
        score=summary.score,
        algorithm_version=summary.algorithm_version,
        contributions=summary.contributions,
        configuration=_object(model.configuration),
    )


def _detection(model: DetectionReadModel) -> DetectionResponse:
    return DetectionResponse(
        source_name=model.source_name,
        source_record_id=model.source_record_id,
        observed_at=model.observed_at,
        geometry=_object(model.geometry),
        confidence=model.confidence,
        intensity=model.intensity,
    )


def _asset(model: ExposedAssetReadModel) -> ExposedAssetResponse:
    return ExposedAssetResponse(
        asset_id=model.asset_id,
        asset_kind=model.asset_kind,
        name=model.name,
        population=model.population,
        capacity=model.capacity,
        source_name=model.source_name,
        source_version=model.source_version,
        geometry=_object(model.geometry),
        distance_meters=model.distance_meters,
        bearing_degrees=model.bearing_degrees,
    )


def _resource(model: SimulatedResourceReadModel) -> SimulatedResourceResponse:
    return SimulatedResourceResponse(
        resource_id=model.resource_id,
        resource_type=model.resource_type,
        capabilities=model.capabilities,
        capacity=model.capacity,
        available=model.available,
        status=model.status,
        geometry=_object(model.geometry),
    )


def _object(value: FrozenJsonObject) -> dict[str, JsonValue]:
    return {key: _json(item) for key, item in value.items()}


def _json(value: FrozenJsonValue) -> JsonValue:
    if isinstance(value, Mapping):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json(item) for item in value]
    return cast(JsonValue, value)
