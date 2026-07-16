import pytest
from pydantic import ValidationError

from wildfireops.config import Settings


def test_default_exposure_and_risk_settings_match_risk_v1_contract() -> None:
    settings = Settings()

    assert settings.exposure_buffer_meters == 10_000.0
    assert settings.risk_algorithm_version == "risk-v1"
    assert settings.risk_proximity_weight == 0.30
    assert settings.risk_population_weight == 0.25
    assert settings.risk_critical_facilities_weight == 0.20
    assert settings.risk_wind_alignment_weight == 0.15
    assert settings.risk_detection_confidence_weight == 0.05
    assert settings.risk_source_freshness_weight == 0.05
    assert settings.risk_population_saturation == 10_000.0
    assert settings.risk_critical_facility_saturation_count == 5.0
    assert settings.risk_wind_speed_saturation_mps == 15.0
    assert settings.risk_fire_freshness_seconds == 21_600.0
    assert settings.risk_weather_freshness_seconds == 3_600.0
    assert settings.risk_weather_search_radius_meters == 100_000.0


@pytest.mark.parametrize("value", (99, 100_001, True, float("nan")))
def test_settings_reject_invalid_exposure_buffer(value: object) -> None:
    with pytest.raises(ValidationError, match="exposure buffer"):
        Settings(exposure_buffer_meters=value)


@pytest.mark.parametrize(
    "field",
    (
        "risk_population_saturation",
        "risk_critical_facility_saturation_count",
        "risk_wind_speed_saturation_mps",
        "risk_fire_freshness_seconds",
        "risk_weather_freshness_seconds",
        "risk_weather_search_radius_meters",
    ),
)
def test_settings_reject_invalid_risk_threshold(field: str) -> None:
    with pytest.raises(ValidationError, match="risk threshold"):
        Settings(**{field: 0})


def test_changing_risk_v1_parameters_requires_an_explicit_version_bump() -> None:
    with pytest.raises(ValidationError, match="version bump"):
        Settings(risk_population_saturation=20_000)
    with pytest.raises(ValidationError, match="version bump"):
        Settings(risk_proximity_weight=0.31, risk_population_weight=0.24)

    changed = Settings(
        risk_algorithm_version="risk-v2",
        risk_population_saturation=20_000,
    )

    assert changed.risk_algorithm_version == "risk-v2"
    assert changed.risk_population_saturation == 20_000


def test_settings_reject_weight_sets_that_do_not_sum_to_one() -> None:
    with pytest.raises(ValidationError, match="sum to 1"):
        Settings(
            risk_algorithm_version="risk-v2",
            risk_proximity_weight=0.4,
        )
