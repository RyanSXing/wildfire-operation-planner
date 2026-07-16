from datetime import UTC, datetime, timedelta

import pytest

from wildfireops.decision.risk import (
    default_risk_config,
    normalize_risk_inputs,
)
from wildfireops.domain.observations import NormalizedObservation, WeatherObservation
from wildfireops.geospatial.exposure import ExposedAssetExposure


_REFERENCE = datetime(2024, 7, 24, 18, tzinfo=UTC)
_LONGITUDE = -121.6
_LATITUDE = 39.8


def _asset(
    asset_id: str,
    *,
    kind: str = "hospital",
    distance: float = 5_000,
    bearing: float | None = 90,
    population: int | None = None,
) -> ExposedAssetExposure:
    return ExposedAssetExposure(
        asset_id=asset_id,
        asset_kind=kind,
        name=asset_id,
        population=population,
        capacity=None,
        source_name="openstreetmap",
        source_version="osm-v1",
        geometry_geojson={"type": "Point", "coordinates": [-121.55, 39.8]},
        raw_metadata={},
        distance_meters=distance,
        bearing_degrees=bearing,
    )


def _detection(
    record_id: str,
    *,
    confidence: float = 0.8,
    observed_at: datetime = _REFERENCE,
) -> NormalizedObservation:
    return NormalizedObservation(
        source_name="nasa_firms",
        source_record_id=record_id,
        observed_at=observed_at,
        longitude=_LONGITUDE,
        latitude=_LATITUDE,
        confidence=confidence,
        intensity=None,
        raw_payload={"record_id": record_id},
    )


def _weather(
    record_id: str,
    *,
    observed_at: datetime = _REFERENCE,
    longitude: float = _LONGITUDE,
    latitude: float = _LATITUDE,
    speed: float = 15,
    direction_from: float = 270,
) -> WeatherObservation:
    return WeatherObservation(
        source_name="nws",
        source_record_id=record_id,
        observed_at=observed_at,
        longitude=longitude,
        latitude=latitude,
        wind_speed_mps=speed,
        wind_direction_degrees=direction_from,
        temperature_celsius=None,
        raw_payload={"record_id": record_id},
    )


def _normalize(
    *,
    exposures: tuple[ExposedAssetExposure, ...] = (),
    detections: tuple[NormalizedObservation, ...] | None = None,
    weather: tuple[WeatherObservation, ...] = (),
):
    return normalize_risk_inputs(
        exposures=exposures,
        detections=((_detection("fire-1"),) if detections is None else detections),
        weather_observations=weather,
        incident_longitude=_LONGITUDE,
        incident_latitude=_LATITUDE,
        reference_at=_REFERENCE,
        exposure_buffer_meters=10_000,
        config=default_risk_config(),
    )


def test_normalization_clamps_exposure_population_facilities_and_confidence() -> None:
    result = _normalize(
        exposures=(
            _asset("community", kind="community", distance=0, population=12_000),
            _asset("hospital", kind="hospital"),
            _asset("station", kind="fire_station"),
            _asset("shelter", kind="shelter"),
            _asset("school", kind="school"),
        ),
        detections=(
            _detection("fire-1", confidence=0.8),
            _detection("fire-2", confidence=1.0),
        ),
    )

    assert result.factors.proximity == 1.0
    assert result.factors.population == 1.0
    assert result.factors.critical_facilities == 0.6
    assert result.factors.detection_confidence == pytest.approx(0.9)
    assert result.factors.wind_alignment == 0.0
    assert result.factors.source_freshness == 0.0
    assert result.raw_evidence["proximity"] == {
        "nearest_distance": 0.0,
        "buffer": 10_000.0,
    }
    assert result.raw_evidence["population"] == {
        "population": 12_000,
        "community_count": 1,
        "saturation_population": 10_000.0,
    }
    assert result.raw_evidence["critical_facilities"] == {
        "count": 3,
        "kinds": ("fire_station", "hospital", "shelter"),
        "saturation_count": 5.0,
    }
    assert result.raw_evidence["detection_confidence"] == {
        "mean": pytest.approx(0.9),
        "detection_count": 2,
    }


def test_population_saturation_handles_arbitrarily_large_nonnegative_counts() -> None:
    result = _normalize(
        exposures=(
            _asset(
                "large-community",
                kind="community",
                population=10**400,
            ),
        )
    )

    assert result.factors.population == 1.0


def test_wind_direction_is_meteorological_from_and_alignment_uses_spread_bearing() -> (
    None
):
    aligned = _normalize(
        exposures=(_asset("east", bearing=90),),
        weather=(_weather("weather-aligned", direction_from=270),),
    )
    opposed = _normalize(
        exposures=(_asset("west", bearing=270),),
        weather=(_weather("weather-opposed", direction_from=270),),
    )

    assert aligned.factors.wind_alignment == pytest.approx(1.0)
    assert opposed.factors.wind_alignment == pytest.approx(0.0, abs=1e-12)
    assert aligned.raw_evidence["wind_alignment"] == {
        "weather_identity": "nws:weather-aligned",
        "speed": 15.0,
        "from": 270.0,
        "spread": 90.0,
        "max_alignment": 1.0,
        "saturation_speed": 15.0,
    }


def test_coincident_asset_is_conservatively_fully_aligned() -> None:
    result = _normalize(
        exposures=(_asset("coincident", distance=0, bearing=None),),
        weather=(_weather("weather", speed=7.5),),
    )

    assert result.factors.wind_alignment == pytest.approx(0.5)
    assert result.raw_evidence["wind_alignment"]["max_alignment"] == 1.0


def test_weather_evidence_remains_honest_when_no_assets_are_exposed() -> None:
    result = _normalize(weather=(_weather("weather"),))

    assert result.factors.wind_alignment == 0.0
    assert result.raw_evidence["wind_alignment"] == {
        "weather_identity": "nws:weather",
        "speed": 15.0,
        "from": 270.0,
        "spread": 90.0,
        "max_alignment": None,
        "saturation_speed": 15.0,
    }


def test_weather_selection_uses_latest_then_distance_then_identity_and_ignores_future() -> (
    None
):
    result = _normalize(
        exposures=(_asset("east"),),
        weather=(
            _weather(
                "future",
                observed_at=_REFERENCE + timedelta(seconds=1),
            ),
            _weather(
                "older-near",
                observed_at=_REFERENCE - timedelta(minutes=2),
            ),
            _weather(
                "latest-farther",
                observed_at=_REFERENCE - timedelta(minutes=1),
                longitude=-121.0,
            ),
            _weather(
                "latest-outside-radius",
                observed_at=_REFERENCE - timedelta(seconds=1),
                longitude=-119.0,
            ),
        ),
    )

    assert result.selected_weather_identity == "nws:latest-farther"

    distance_tie_break = _normalize(
        exposures=(_asset("east"),),
        weather=(
            _weather("alpha-far", longitude=-121.0),
            _weather("zulu-near"),
        ),
    )
    assert distance_tie_break.selected_weather_identity == "nws:zulu-near"

    tie = _normalize(
        exposures=(_asset("east"),),
        weather=(
            _weather("zulu"),
            _weather("alpha"),
        ),
    )
    assert tie.selected_weather_identity == "nws:alpha"


def test_freshness_uses_nonfuture_fire_and_weather_and_missing_weather_is_zero() -> (
    None
):
    result = _normalize(
        detections=(
            _detection("future", observed_at=_REFERENCE + timedelta(seconds=1)),
            _detection("fire", observed_at=_REFERENCE - timedelta(hours=3)),
        ),
        weather=(
            _weather(
                "weather",
                observed_at=_REFERENCE - timedelta(minutes=30),
            ),
        ),
    )

    assert result.factors.source_freshness == pytest.approx(0.5)
    assert result.raw_evidence["source_freshness"] == {
        "fire_age": 10_800.0,
        "weather_age": 1_800.0,
        "stale_thresholds": {
            "fire_seconds": 21_600.0,
            "weather_seconds": 3_600.0,
        },
    }
    missing = _normalize()
    assert missing.factors.source_freshness == 0.0
    assert missing.raw_evidence["source_freshness"]["weather_age"] is None


@pytest.mark.parametrize("population", (None, -1))
def test_exposed_community_requires_nonnegative_known_population(
    population: int | None,
) -> None:
    with pytest.raises(ValueError, match="community.*population"):
        _normalize(
            exposures=(
                _asset("invalid-community", kind="community", population=population),
            )
        )


@pytest.mark.parametrize(
    "detections",
    (
        (),
        (
            _detection(
                "future",
                observed_at=_REFERENCE + timedelta(seconds=1),
            ),
        ),
    ),
)
def test_normalization_requires_a_nonfuture_incident_detection(
    detections: tuple[NormalizedObservation, ...],
) -> None:
    with pytest.raises(ValueError, match="active incident.*detection"):
        _normalize(detections=detections)
