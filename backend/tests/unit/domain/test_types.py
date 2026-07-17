from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Any

import pytest

from wildfireops.domain.observations import (
    NormalizedObservation,
    SourceObservation,
    WeatherObservation,
)
from wildfireops.domain.operations import DemandPoint, ResourceUnit
from wildfireops.domain.scenarios import (
    ResourceOverride,
    RoadClosure,
    ScenarioVersion,
    WeatherOverride,
)


def test_observation_identity_is_source_scoped() -> None:
    record = NormalizedObservation(
        source_name="nasa_firms",
        source_record_id="viirs-42",
        observed_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
        longitude=-121.6,
        latitude=39.8,
        confidence=0.9,
        intensity=18.4,
        raw_payload={"satellite": "NOAA-20"},
    )
    assert record.identity == "nasa_firms:viirs-42"


def test_scenario_version_is_immutable() -> None:
    scenario = ScenarioVersion(
        scenario_id="scenario-1",
        version=1,
        incident_snapshot_id="incident-snapshot-1",
        road_closures=(RoadClosure(edge_id="edge-9"),),
        weather_overrides=(),
        resource_overrides=(),
    )

    with pytest.raises(FrozenInstanceError):
        scenario.version = 2


def make_normalized_observation(**changes: Any) -> NormalizedObservation:
    values = {
        "source_name": "nasa_firms",
        "source_record_id": "viirs-42",
        "observed_at": datetime(2024, 7, 24, 18, tzinfo=UTC),
        "longitude": -121.6,
        "latitude": 39.8,
        "confidence": 0.9,
        "intensity": 18.4,
        "raw_payload": {"satellite": "NOAA-20"},
    }
    values.update(changes)
    return NormalizedObservation(**values)


@pytest.mark.parametrize("field", ["source_name", "source_record_id"])
def test_observation_requires_source_identity(field: str) -> None:
    with pytest.raises(ValueError, match="source identity is required"):
        make_normalized_observation(**{field: ""})


@pytest.mark.parametrize("longitude", [-180.1, 180.1])
def test_observation_rejects_longitude_outside_valid_range(
    longitude: float,
) -> None:
    with pytest.raises(ValueError, match="longitude is outside valid range"):
        make_normalized_observation(longitude=longitude)


@pytest.mark.parametrize("latitude", [-90.1, 90.1])
def test_observation_rejects_latitude_outside_valid_range(latitude: float) -> None:
    with pytest.raises(ValueError, match="latitude is outside valid range"):
        make_normalized_observation(latitude=latitude)


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_observation_rejects_confidence_outside_valid_range(
    confidence: float,
) -> None:
    with pytest.raises(ValueError, match="confidence is outside valid range"):
        make_normalized_observation(confidence=confidence)


def make_weather_observation(**changes: Any) -> WeatherObservation:
    values = {
        "source_name": "nws",
        "source_record_id": "forecast-42",
        "observed_at": datetime(2024, 7, 24, 18, tzinfo=UTC),
        "longitude": -121.6,
        "latitude": 39.8,
        "wind_speed_mps": 5.0,
        "wind_direction_degrees": 270.0,
        "temperature_celsius": 32.0,
        "raw_payload": {"office": "STO"},
    }
    values.update(changes)
    return WeatherObservation(**values)


OBSERVATION_FACTORIES = (make_normalized_observation, make_weather_observation)


class UnknownOffset(tzinfo):
    def utcoffset(self, dt: datetime | None) -> None:
        return None


@pytest.mark.parametrize("observation_factory", OBSERVATION_FACTORIES)
@pytest.mark.parametrize(
    "observed_at",
    [
        datetime(2024, 7, 24, 18),
        datetime(2024, 7, 24, 18, tzinfo=UnknownOffset()),
        datetime(2024, 7, 24, 18, tzinfo=timezone(timedelta(hours=-7))),
    ],
)
def test_observations_reject_timestamps_without_zero_utc_offset(
    observation_factory: Any,
    observed_at: datetime,
) -> None:
    with pytest.raises(ValueError, match="observed_at must be UTC"):
        observation_factory(observed_at=observed_at)


@pytest.mark.parametrize("observation_factory", OBSERVATION_FACTORIES)
@pytest.mark.parametrize(
    "observed_at",
    [
        datetime(2024, 7, 24, 18, tzinfo=UTC),
        datetime(
            2024,
            7,
            24,
            18,
            tzinfo=timezone(timedelta(0), name="zero-offset"),
        ),
    ],
)
def test_observations_accept_zero_utc_offset(
    observation_factory: Any,
    observed_at: datetime,
) -> None:
    assert observation_factory(observed_at=observed_at).observed_at == observed_at


@pytest.mark.parametrize("observation_factory", OBSERVATION_FACTORIES)
def test_observation_payload_rejects_top_level_mutation(
    observation_factory: Any,
) -> None:
    record = observation_factory(raw_payload={"status": "active"})

    with pytest.raises(TypeError):
        record.raw_payload["status"] = "inactive"


@pytest.mark.parametrize("observation_factory", OBSERVATION_FACTORIES)
def test_observation_payload_rejects_nested_mapping_mutation(
    observation_factory: Any,
) -> None:
    record = observation_factory(raw_payload={"details": {"status": "active"}})

    with pytest.raises(TypeError):
        record.raw_payload["details"]["status"] = "inactive"


@pytest.mark.parametrize("observation_factory", OBSERVATION_FACTORIES)
def test_observation_payload_rejects_nested_sequence_mutation(
    observation_factory: Any,
) -> None:
    record = observation_factory(raw_payload={"labels": ["active"]})

    with pytest.raises(TypeError):
        record.raw_payload["labels"][0] = "inactive"


@pytest.mark.parametrize("observation_factory", OBSERVATION_FACTORIES)
def test_observation_payload_is_isolated_from_caller_mutation(
    observation_factory: Any,
) -> None:
    raw_payload: dict[str, Any] = {
        "details": {"status": "active", "labels": ["initial"]}
    }
    record = observation_factory(raw_payload=raw_payload)

    raw_payload["added"] = True
    raw_payload["details"]["status"] = "caller-mutated"
    raw_payload["details"]["labels"].append("caller-mutated")

    assert "added" not in record.raw_payload
    assert record.raw_payload["details"] == {
        "status": "active",
        "labels": ("initial",),
    }


@pytest.mark.parametrize("observation_factory", OBSERVATION_FACTORIES)
def test_observation_payload_rejects_unsupported_json_values(
    observation_factory: Any,
) -> None:
    with pytest.raises(
        ValueError,
        match="raw_payload contains unsupported JSON value: set",
    ):
        observation_factory(raw_payload={"unsupported": {"not-json"}})


def test_weather_observation_is_a_source_observation() -> None:
    record: SourceObservation = make_weather_observation()
    assert record.identity == "nws:forecast-42"


@pytest.mark.parametrize("field", ["source_name", "source_record_id"])
def test_weather_observation_requires_source_identity(field: str) -> None:
    with pytest.raises(ValueError, match="source identity is required"):
        make_weather_observation(**{field: ""})


@pytest.mark.parametrize("longitude", [-180.1, 180.1])
def test_weather_observation_rejects_longitude_outside_valid_range(
    longitude: float,
) -> None:
    with pytest.raises(ValueError, match="longitude is outside valid range"):
        make_weather_observation(longitude=longitude)


@pytest.mark.parametrize("latitude", [-90.1, 90.1])
def test_weather_observation_rejects_latitude_outside_valid_range(
    latitude: float,
) -> None:
    with pytest.raises(ValueError, match="latitude is outside valid range"):
        make_weather_observation(latitude=latitude)


def test_weather_observation_rejects_negative_wind_speed() -> None:
    with pytest.raises(ValueError, match="wind speed cannot be negative"):
        make_weather_observation(wind_speed_mps=-0.1)


@pytest.mark.parametrize("direction", [-0.1, 360.0])
def test_weather_observation_rejects_direction_outside_valid_range(
    direction: float,
) -> None:
    with pytest.raises(ValueError, match="wind direction is outside valid range"):
        make_weather_observation(wind_direction_degrees=direction)


def test_resource_unit_requires_positive_capacity() -> None:
    with pytest.raises(ValueError, match="resource capacity must be positive"):
        ResourceUnit("crew-1", frozenset({"fireline"}), 0, True, -121.6, 39.8)


def test_resource_unit_requires_capabilities() -> None:
    with pytest.raises(ValueError, match="resource capabilities are required"):
        ResourceUnit("crew-1", frozenset(), 1, True, -121.6, 39.8)


def test_demand_point_requires_positive_capacity() -> None:
    with pytest.raises(ValueError, match="required capacity must be positive"):
        DemandPoint("asset-1", "fireline", 0, 1.0, -121.6, 39.8)


def test_demand_point_rejects_negative_weighted_risk() -> None:
    with pytest.raises(ValueError, match="weighted risk cannot be negative"):
        DemandPoint("asset-1", "fireline", 1, -0.1, -121.6, 39.8)


def test_scenario_version_requires_positive_version() -> None:
    with pytest.raises(ValueError, match="scenario version must be positive"):
        ScenarioVersion("scenario-1", 0, "snapshot-1", (), (), ())


def test_weather_override_rejects_negative_wind_speed() -> None:
    with pytest.raises(ValueError, match="wind speed cannot be negative"):
        WeatherOverride(wind_speed_mps=-0.1, wind_direction_degrees=180.0)


@pytest.mark.parametrize("direction", [-0.1, 360.0])
def test_weather_override_rejects_direction_outside_valid_range(
    direction: float,
) -> None:
    with pytest.raises(ValueError, match="wind direction is outside valid range"):
        WeatherOverride(wind_speed_mps=5.0, wind_direction_degrees=direction)


def test_scenario_version_uses_tuple_overlays() -> None:
    scenario = ScenarioVersion(
        scenario_id="scenario-1",
        version=1,
        incident_snapshot_id="snapshot-1",
        road_closures=(RoadClosure(edge_id="edge-9"),),
        weather_overrides=(WeatherOverride(5.0, 180.0),),
        resource_overrides=(ResourceOverride("crew-1", False),),
    )

    assert isinstance(scenario.road_closures, tuple)
    assert isinstance(scenario.weather_overrides, tuple)
    assert isinstance(scenario.resource_overrides, tuple)
