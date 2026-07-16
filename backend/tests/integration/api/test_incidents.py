from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import FastAPI
from geoalchemy2.elements import WKTElement
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wildfireops.main import create_app
from wildfireops.persistence.decision_models import IncidentSnapshotModel
from wildfireops.persistence.observed_models import (
    IncidentDetectionModel,
    SourceObservationModel,
    WildfireIncidentModel,
)


_REFERENCE = datetime(2024, 7, 24, 18, 30, tzinfo=UTC)
_HIGH_ID = UUID("00000000-0000-0000-0000-000000000801")
_LOW_ID = UUID("00000000-0000-0000-0000-000000000802")


def _risk(score: float, contribution: float) -> dict[str, object]:
    return {
        "config_version": "risk-v1",
        "score": score,
        "factors": [
            {
                "name": "proximity",
                "raw": {"nearest_distance": 0.0},
                "normalized_value": 1.0,
                "weight": 0.3,
                "contribution": round(contribution, 1),
            }
        ],
    }


async def _seed_incident(
    session: AsyncSession,
    *,
    incident_id: UUID,
    name: str,
    score: float,
    last_observed_at: datetime,
    asset_count: int,
) -> None:
    session.add(
        WildfireIncidentModel(
            id=incident_id,
            status="active",
            risk_score=score,
            geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
            first_observed_at=last_observed_at - timedelta(hours=1),
            last_observed_at=last_observed_at,
        )
    )
    await session.flush()
    session.add(
        IncidentSnapshotModel(
            incident_id=incident_id,
            snapshot_version=1,
            source_versions={"observation_inputs": []},
            incident_state={
                "name": name,
                "status": "active",
                "geometry_geojson": {
                    "type": "Point",
                    "coordinates": [-121.6, 39.8],
                },
                "first_observed_at": (
                    last_observed_at - timedelta(hours=1)
                ).isoformat().replace("+00:00", "Z"),
                "last_observed_at": last_observed_at.isoformat().replace(
                    "+00:00", "Z"
                ),
                "reference_at": _REFERENCE.isoformat().replace("+00:00", "Z"),
                "detection_identities": [],
                "risk": _risk(score, score * 0.3),
            },
            asset_state=[{"asset_id": f"asset-{index}"} for index in range(asset_count)],
            resource_state=[],
            captured_at=_REFERENCE,
        )
    )
    await session.flush()


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
async def test_incident_list_is_risk_ordered_with_explanations_and_freshness(
    db_session: AsyncSession,
) -> None:
    await _seed_incident(
        db_session,
        incident_id=_LOW_ID,
        name="Bear Ridge",
        score=61.0,
        last_observed_at=_REFERENCE - timedelta(hours=7),
        asset_count=1,
    )
    await _seed_incident(
        db_session,
        incident_id=_HIGH_ID,
        name="Redwood Creek",
        score=82.0,
        last_observed_at=_REFERENCE - timedelta(minutes=12),
        asset_count=3,
    )

    app = _test_app(db_session)
    app.state.clock = lambda: datetime(2030, 1, 1, tzinfo=UTC)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/incidents")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": str(_HIGH_ID),
                "name": "Redwood Creek",
                "risk": {
                    "score": 82.0,
                    "algorithmVersion": "risk-v1",
                    "contributions": [
                        {
                            "name": "proximity",
                            "rawValue": {"nearest_distance": 0.0},
                            "normalizedValue": 1.0,
                            "weight": 0.3,
                            "contribution": 24.6,
                        }
                    ],
                },
                "exposedAssetCount": 3,
                "lastObservedAt": "2024-07-24T18:18:00Z",
                "freshness": "fresh",
            },
            {
                "id": str(_LOW_ID),
                "name": "Bear Ridge",
                "risk": {
                    "score": 61.0,
                    "algorithmVersion": "risk-v1",
                    "contributions": [
                        {
                            "name": "proximity",
                            "rawValue": {"nearest_distance": 0.0},
                            "normalizedValue": 1.0,
                            "weight": 0.3,
                            "contribution": 18.3,
                        }
                    ],
                },
                "exposedAssetCount": 1,
                "lastObservedAt": "2024-07-24T11:30:00Z",
                "freshness": "stale",
            },
        ]
    }


@pytest.mark.asyncio
async def test_incident_detail_returns_the_complete_snapshot_and_detections(
    db_session: AsyncSession,
) -> None:
    observed_at = _REFERENCE - timedelta(minutes=12)
    observation = SourceObservationModel(
        source_name="nasa_firms",
        source_record_id="fire-801",
        observation_kind="fire",
        observed_at=observed_at,
        geometry=WKTElement("POINT(-121.61 39.81)", srid=4326),
        confidence=0.91,
        intensity=18.4,
        raw_payload={"do_not_expose": "raw-source-payload"},
    )
    incident = WildfireIncidentModel(
        id=_HIGH_ID,
        status="active",
        risk_score=82.0,
        geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
        first_observed_at=observed_at - timedelta(hours=1),
        last_observed_at=observed_at,
    )
    db_session.add_all([observation, incident])
    await db_session.flush()
    db_session.add(
        IncidentDetectionModel(
            incident_id=incident.id,
            observation_id=observation.id,
        )
    )
    snapshot = IncidentSnapshotModel(
        incident_id=incident.id,
        snapshot_version=1,
        source_versions={
            "observation_inputs": [
                {
                    "source_name": "nasa_firms",
                    "source_version": "viirs-2024-07-24",
                    "record_ids": ["fire-801"],
                    "latest_observed_at": "2024-07-24T18:18:00Z",
                }
            ],
            "asset_inputs": [
                {"source_name": "census", "source_version": "2023-acs5"}
            ],
        },
        incident_state={
            "name": "Redwood Creek",
            "status": "active",
            "geometry_geojson": {
                "type": "Point",
                "coordinates": [-121.6, 39.8],
            },
            "first_observed_at": "2024-07-24T17:18:00Z",
            "last_observed_at": "2024-07-24T18:18:00Z",
            "reference_at": "2024-07-24T18:30:00Z",
            "detection_identities": ["nasa_firms:fire-801"],
            "risk": {
                **_risk(82.0, 24.6),
                "config": {
                    "algorithm_version": "risk-v1",
                    "fire_freshness_seconds": 21_600.0,
                },
            },
        },
        asset_state=[
            {
                "asset_id": "community-1",
                "asset_kind": "community",
                "name": "Forest Ranch",
                "population": 1_184,
                "capacity": None,
                "source_name": "census",
                "source_version": "2023-acs5",
                "geometry_geojson": {
                    "type": "Point",
                    "coordinates": [-121.65, 39.86],
                },
                "distance_meters": 7_200.0,
                "bearing_degrees": 315.0,
                "raw_metadata": {"internal": "not-needed-by-operator"},
            }
        ],
        resource_state=[
            {
                "resource_id": "engine-1",
                "resource_type": "engine",
                "capabilities": ["medical", "water"],
                "capacity": 4,
                "available": True,
                "status": "available",
                "geometry_geojson": {
                    "type": "Point",
                    "coordinates": [-121.7, 39.7],
                },
                "raw_metadata": {"simulated": True},
            },
            {
                "resource_id": "not-actually-simulated",
                "raw_metadata": {"simulated": 1},
            },
        ],
        captured_at=_REFERENCE,
    )
    db_session.add(snapshot)
    await db_session.flush()

    app = _test_app(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/api/incidents/{_HIGH_ID}")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(_HIGH_ID),
        "name": "Redwood Creek",
        "status": "active",
        "snapshotId": str(snapshot.id),
        "snapshotVersion": 1,
        "geometry": {"type": "Point", "coordinates": [-121.6, 39.8]},
        "firstObservedAt": "2024-07-24T17:18:00Z",
        "lastObservedAt": "2024-07-24T18:18:00Z",
        "freshness": "fresh",
        "risk": {
            "score": 82.0,
            "algorithmVersion": "risk-v1",
            "configuration": {
                "algorithm_version": "risk-v1",
                "fire_freshness_seconds": 21_600.0,
            },
            "contributions": [
                {
                    "name": "proximity",
                    "rawValue": {"nearest_distance": 0.0},
                    "normalizedValue": 1.0,
                    "weight": 0.3,
                    "contribution": 24.6,
                }
            ],
        },
        "detections": [
            {
                "sourceName": "nasa_firms",
                "sourceRecordId": "fire-801",
                "observedAt": "2024-07-24T18:18:00Z",
                "geometry": {
                    "type": "Point",
                    "coordinates": [-121.61, 39.81],
                },
                "confidence": 0.91,
                "intensity": 18.4,
            }
        ],
        "exposedAssets": [
            {
                "assetId": "community-1",
                "assetKind": "community",
                "name": "Forest Ranch",
                "population": 1_184,
                "capacity": None,
                "sourceName": "census",
                "sourceVersion": "2023-acs5",
                "geometry": {
                    "type": "Point",
                    "coordinates": [-121.65, 39.86],
                },
                "distanceMeters": 7_200.0,
                "bearingDegrees": 315.0,
            }
        ],
        "simulatedResources": [
            {
                "resourceId": "engine-1",
                "resourceType": "engine",
                "capabilities": ["medical", "water"],
                "capacity": 4,
                "available": True,
                "status": "available",
                "geometry": {
                    "type": "Point",
                    "coordinates": [-121.7, 39.7],
                },
                "simulated": True,
                "simulationLabel": "simulated",
            }
        ],
        "sourceVersions": snapshot.source_versions,
    }


@pytest.mark.asyncio
async def test_missing_incident_uses_the_stable_error_contract(
    db_session: AsyncSession,
) -> None:
    missing_id = UUID("00000000-0000-0000-0000-000000000899")
    app = _test_app(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/api/incidents/{missing_id}")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "incident_not_found",
            "message": "Incident was not found",
            "details": {"incidentId": str(missing_id)},
        }
    }


@pytest.mark.asyncio
async def test_malformed_incident_id_is_a_stable_not_found_error(
    db_session: AsyncSession,
) -> None:
    app = _test_app(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/incidents/not-a-uuid")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "incident_not_found",
            "message": "Incident was not found",
            "details": {"incidentId": "not-a-uuid"},
        }
    }


@pytest.mark.asyncio
async def test_incident_list_orders_by_denormalized_risk_then_uuid(
    db_session: AsyncSession,
) -> None:
    await _seed_incident(
        db_session,
        incident_id=_LOW_ID,
        name="Bear Ridge",
        score=61.0,
        last_observed_at=_REFERENCE,
        asset_count=1,
    )
    await _seed_incident(
        db_session,
        incident_id=_HIGH_ID,
        name="Redwood Creek",
        score=82.0,
        last_observed_at=_REFERENCE,
        asset_count=1,
    )
    low_incident = await db_session.get(WildfireIncidentModel, _LOW_ID)
    assert low_incident is not None
    low_incident.risk_score = 95.0
    await db_session.flush()

    app = _test_app(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/incidents")
        high_incident = await db_session.get(WildfireIncidentModel, _HIGH_ID)
        assert high_incident is not None
        high_incident.risk_score = 95.0
        await db_session.flush()
        tied_response = await client.get("/api/incidents")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [
        str(_LOW_ID),
        str(_HIGH_ID),
    ]
    assert [item["id"] for item in tied_response.json()["items"]] == [
        str(_HIGH_ID),
        str(_LOW_ID),
    ]


@pytest.mark.asyncio
async def test_timeline_is_snapshot_ordered_and_reconstructs_historical_detections(
    db_session: AsyncSession,
) -> None:
    early_at = datetime(2024, 7, 24, 12, tzinfo=UTC)
    late_at = datetime(2024, 7, 24, 12, 30, tzinfo=UTC)
    early = SourceObservationModel(
        source_name="nasa_firms",
        source_record_id="fire-early",
        observation_kind="fire",
        observed_at=early_at,
        geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
        confidence=0.8,
        intensity=None,
        raw_payload={},
    )
    late = SourceObservationModel(
        source_name="nasa_firms",
        source_record_id="fire-late",
        observation_kind="fire",
        observed_at=late_at,
        geometry=WKTElement("POINT(-121.61 39.81)", srid=4326),
        confidence=0.9,
        intensity=12.0,
        raw_payload={},
    )
    incident = WildfireIncidentModel(
        id=_HIGH_ID,
        status="active",
        risk_score=80.0,
        geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
        first_observed_at=early_at,
        last_observed_at=late_at,
    )
    db_session.add_all([early, late, incident])
    await db_session.flush()

    def state(
        *,
        last_observed_at: str,
        reference_at: str,
        identities: list[str],
        score: float,
    ) -> dict[str, object]:
        return {
            "status": "active",
            "geometry_geojson": {
                "type": "Point",
                "coordinates": [-121.6, 39.8],
            },
            "first_observed_at": "2024-07-24T12:00:00Z",
            "last_observed_at": last_observed_at,
            "reference_at": reference_at,
            "detection_identities": identities,
            "risk": _risk(score, score * 0.3),
        }

    first = IncidentSnapshotModel(
        incident_id=incident.id,
        snapshot_version=1,
        source_versions={},
        incident_state=state(
            last_observed_at="2024-07-24T12:00:00Z",
            reference_at="2024-07-24T18:00:00Z",
            identities=["nasa_firms:fire-early"],
            score=70.0,
        ),
        asset_state=[{"asset_id": "asset-1"}],
        resource_state=[],
        captured_at=_REFERENCE,
    )
    second = IncidentSnapshotModel(
        incident_id=incident.id,
        snapshot_version=2,
        source_versions={},
        incident_state=state(
            last_observed_at="2024-07-24T12:30:00Z",
            reference_at="2024-07-24T18:30:01Z",
            identities=["nasa_firms:fire-early", "nasa_firms:fire-late"],
            score=80.0,
        ),
        asset_state=[{"asset_id": "asset-1"}, {"asset_id": "asset-2"}],
        resource_state=[],
        captured_at=_REFERENCE,
    )
    db_session.add_all([second, first])
    await db_session.flush()

    app = _test_app(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/api/incidents/{_HIGH_ID}/timeline")

    assert response.status_code == 200
    payload = response.json()
    assert [item["snapshotId"] for item in payload["items"]] == [
        str(first.id),
        str(second.id),
    ]
    assert [item["snapshotVersion"] for item in payload["items"]] == [1, 2]
    assert [
        [detection["sourceRecordId"] for detection in item["detections"]]
        for item in payload["items"]
    ] == [["fire-early"], ["fire-early", "fire-late"]]
    assert [item["freshness"] for item in payload["items"]] == [
        "fresh",
        "stale",
    ]
    assert [item["exposedAssetCount"] for item in payload["items"]] == [1, 2]
    assert payload["items"][0]["referenceAt"] == "2024-07-24T18:00:00Z"
    assert payload["items"][0]["capturedAt"] == "2024-07-24T18:30:00Z"


@pytest.mark.asyncio
async def test_detail_uses_max_snapshot_version_and_stable_name_fallback(
    db_session: AsyncSession,
) -> None:
    incident_id = UUID("12345678-0000-0000-0000-000000000803")
    await _seed_incident(
        db_session,
        incident_id=incident_id,
        name="Older Name",
        score=40.0,
        last_observed_at=_REFERENCE,
        asset_count=0,
    )
    latest = IncidentSnapshotModel(
        incident_id=incident_id,
        snapshot_version=2,
        source_versions={},
        incident_state={
            "status": "active",
            "geometry_geojson": {
                "type": "Point",
                "coordinates": [-121.6, 39.8],
            },
            "first_observed_at": "2024-07-24T17:30:00Z",
            "last_observed_at": "2024-07-24T18:30:00Z",
            "reference_at": "2024-07-24T18:30:00Z",
            "detection_identities": [],
            "risk": {
                **_risk(55.0, 16.5),
                "config": {"algorithm_version": "risk-v1"},
            },
        },
        asset_state=[],
        resource_state=[],
        captured_at=_REFERENCE - timedelta(days=1),
    )
    db_session.add(latest)
    await db_session.flush()

    app = _test_app(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/api/incidents/{incident_id}")

    assert response.status_code == 200
    assert response.json()["snapshotId"] == str(latest.id)
    assert response.json()["snapshotVersion"] == 2
    assert response.json()["name"] == "Incident 12345678"
    assert response.json()["risk"]["score"] == 55.0
