from dataclasses import FrozenInstanceError
from math import inf, nan
from uuid import UUID

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.geospatial.exposure import ExposedAssetExposure
from wildfireops.persistence.exposures import ExposureRepository
from wildfireops.persistence.observed_models import (
    ExposedAssetModel,
    WildfireIncidentModel,
)


_INCIDENT_ID = UUID("00000000-0000-0000-0000-000000000701")
_LONGITUDE = -121.6
_LATITUDE = 39.8


async def _seed_incident(session: AsyncSession) -> None:
    await session.execute(delete(ExposedAssetModel))
    await session.execute(
        text(
            "INSERT INTO wildfire_incidents "
            "(id, status, geometry, first_observed_at, last_observed_at) "
            "VALUES (:id, 'active', ST_SetSRID(ST_Point(:lon, :lat), 4326), "
            "'2024-07-24T18:00:00Z', '2024-07-24T18:00:00Z')"
        ),
        {"id": _INCIDENT_ID, "lon": _LONGITUDE, "lat": _LATITUDE},
    )


async def _seed_asset(
    session: AsyncSession,
    *,
    asset_id: str,
    asset_kind: str,
    distance_meters: float,
    bearing_degrees: float,
    population: int | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO exposed_assets "
            "(id, asset_id, asset_kind, name, population, capacity, source_name, "
            "source_version, geometry, raw_metadata) "
            "VALUES (gen_random_uuid(), :asset_id, :asset_kind, :name, :population, "
            "25, 'openstreetmap', 'osm-2024-07-20', "
            "ST_Project(ST_SetSRID(ST_Point(:lon, :lat), 4326)::geography, "
            "CAST(:distance AS double precision), radians(:bearing))::geometry, "
            "CAST(:metadata AS jsonb))"
        ),
        {
            "asset_id": asset_id,
            "asset_kind": asset_kind,
            "name": f"Asset {asset_id}",
            "population": population,
            "lon": _LONGITUDE,
            "lat": _LATITUDE,
            "distance": distance_meters,
            "bearing": bearing_degrees,
            "metadata": '{"verified":true}',
        },
    )


@pytest.mark.asyncio
async def test_exposure_uses_geography_and_includes_the_exact_boundary(
    db_session: AsyncSession,
) -> None:
    await _seed_incident(db_session)
    await _seed_asset(
        db_session,
        asset_id="community-boundary",
        asset_kind="community",
        distance_meters=10_000,
        bearing_degrees=90,
        population=4_200,
    )
    await _seed_asset(
        db_session,
        asset_id="hospital-inside",
        asset_kind="hospital",
        distance_meters=5_000,
        bearing_degrees=0,
    )
    await _seed_asset(
        db_session,
        asset_id="shelter-outside",
        asset_kind="shelter",
        distance_meters=10_001,
        bearing_degrees=180,
    )

    result = await ExposureRepository().find_for_incident(
        db_session,
        _INCIDENT_ID,
        10_000,
    )

    assert [item.asset_id for item in result] == [
        "hospital-inside",
        "community-boundary",
    ]
    boundary = result[1]
    assert boundary.distance_meters == pytest.approx(10_000, abs=0.01)
    assert boundary.bearing_degrees == pytest.approx(90, abs=0.01)
    assert boundary.geometry_geojson["type"] == "Point"
    assert boundary.source_name == "openstreetmap"
    assert boundary.source_version == "osm-2024-07-20"
    assert boundary.raw_metadata == {"verified": True}


@pytest.mark.asyncio
async def test_equal_distance_exposures_are_ordered_by_stable_asset_id(
    db_session: AsyncSession,
) -> None:
    await _seed_incident(db_session)
    await _seed_asset(
        db_session,
        asset_id="tie-zulu",
        asset_kind="hospital",
        distance_meters=4_000,
        bearing_degrees=45,
    )
    await _seed_asset(
        db_session,
        asset_id="tie-alpha",
        asset_kind="shelter",
        distance_meters=4_000,
        bearing_degrees=45,
    )

    result = await ExposureRepository().find_for_incident(
        db_session,
        _INCIDENT_ID,
        10_000,
    )

    assert [item.asset_id for item in result] == ["tie-alpha", "tie-zulu"]


@pytest.mark.asyncio
@pytest.mark.parametrize("buffer", (99, 100_001, nan, inf, True, "1000"))
async def test_exposure_rejects_invalid_buffers_before_querying(
    db_session: AsyncSession,
    buffer: object,
) -> None:
    with pytest.raises(ValueError, match="buffer_meters"):
        await ExposureRepository().find_for_incident(
            db_session,
            _INCIDENT_ID,
            buffer,  # type: ignore[arg-type]
        )


def test_exposure_result_is_recursively_immutable() -> None:
    exposure = ExposedAssetExposure(
        asset_id="asset-1",
        asset_kind="hospital",
        name="Hospital",
        population=None,
        capacity=20,
        source_name="openstreetmap",
        source_version="osm-v1",
        geometry_geojson={"type": "Point", "coordinates": [-121.6, 39.8]},
        raw_metadata={"tags": {"emergency": "yes"}},
        distance_meters=0,
        bearing_degrees=None,
    )

    with pytest.raises(FrozenInstanceError):
        exposure.distance_meters = 1  # type: ignore[misc]
    with pytest.raises(TypeError):
        exposure.raw_metadata["changed"] = True  # type: ignore[index]
    nested = exposure.raw_metadata["tags"]
    assert not isinstance(nested, str)
    with pytest.raises(TypeError):
        nested["emergency"] = "no"  # type: ignore[index]


@pytest.mark.asyncio
async def test_geography_expression_index_exists_and_matches_model_metadata(
    db_session: AsyncSession,
) -> None:
    index_definition = await db_session.scalar(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = current_schema() "
            "AND tablename = 'exposed_assets' "
            "AND indexname = 'ix_exposed_assets_geometry_geography'"
        )
    )

    assert index_definition is not None
    assert "USING gist" in index_definition
    assert "geography" in index_definition
    assert "ix_exposed_assets_geometry_geography" in {
        index.name for index in ExposedAssetModel.__table__.indexes
    }


@pytest.mark.asyncio
async def test_missing_incident_returns_no_exposures(
    db_session: AsyncSession,
) -> None:
    assert not await db_session.scalar(select(WildfireIncidentModel.id))

    result = await ExposureRepository().find_for_incident(
        db_session,
        _INCIDENT_ID,
        10_000,
    )

    assert result == ()
