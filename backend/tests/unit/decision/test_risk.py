from dataclasses import FrozenInstanceError, replace
from math import inf, nan

import pytest

from wildfireops.decision.risk import (
    RiskBreakdown,
    RiskContribution,
    RiskFactors,
    default_risk_config,
    score_risk,
    serialize_risk_breakdown,
    serialize_risk_config,
)


def test_risk_breakdown_sums_to_total_in_stable_factor_order() -> None:
    factors = RiskFactors(
        proximity=0.8,
        population=0.6,
        critical_facilities=0.5,
        wind_alignment=0.75,
        detection_confidence=0.9,
        source_freshness=1.0,
    )

    result = score_risk(factors, default_risk_config())

    assert result.score == 69.75
    assert sum(item.contribution for item in result.contributions) == pytest.approx(
        result.score
    )
    assert [item.name for item in result.contributions] == [
        "proximity",
        "population",
        "critical_facilities",
        "wind_alignment",
        "detection_confidence",
        "source_freshness",
    ]
    assert [item.weight for item in result.contributions] == [
        0.30,
        0.25,
        0.20,
        0.15,
        0.05,
        0.05,
    ]
    assert result.algorithm_version == "risk-v1"


@pytest.mark.parametrize("value", (-0.000001, 1.000001, nan, inf, -inf, True))
def test_risk_factors_reject_nonfinite_bool_and_out_of_range_values(
    value: object,
) -> None:
    with pytest.raises(ValueError, match="proximity"):
        RiskFactors(
            proximity=value,  # type: ignore[arg-type]
            population=0.0,
            critical_facilities=0.0,
            wind_alignment=0.0,
            detection_confidence=0.0,
            source_freshness=0.0,
        )


def test_risk_factor_boundaries_are_inclusive_and_values_are_frozen() -> None:
    factors = RiskFactors(0, 1, 0, 1, 0, 1)

    assert factors.proximity == 0.0
    assert factors.population == 1.0
    with pytest.raises(FrozenInstanceError):
        factors.proximity = 0.5  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("proximity_weight", -0.01),
        ("proximity_weight", nan),
        ("proximity_weight", inf),
        ("proximity_weight", True),
        ("proximity_weight", 0.31),
    ),
)
def test_risk_config_rejects_invalid_weights(field: str, value: object) -> None:
    with pytest.raises(ValueError, match="weight"):
        replace(default_risk_config(), **{field: value})


def test_weight_sum_validation_precedes_registered_version_binding() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        replace(
            default_risk_config(),
            proximity_weight=0.30 + 1.0001e-9,
        )

    with pytest.raises(ValueError, match="registered parameters"):
        replace(
            default_risk_config(),
            proximity_weight=0.30 + 1e-9,
        )


@pytest.mark.parametrize(
    "changes",
    (
        {"proximity_weight": 0.31, "population_weight": 0.24},
        {"population_saturation": 20_000},
        {"weather_search_radius_meters": 50_000},
    ),
)
def test_risk_v1_rejects_any_change_to_its_registered_parameters(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="risk-v1.*registered parameters"):
        replace(default_risk_config(), **changes)


def test_unknown_risk_algorithm_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown risk algorithm version.*risk-v2"):
        replace(default_risk_config(), algorithm_version="risk-v2")


def test_rounding_occurs_only_in_the_canonical_serializer() -> None:
    factors = RiskFactors(0.123456789, 0, 0, 0, 0, 0)

    result = score_risk(factors, default_risk_config())
    serialized = serialize_risk_breakdown(result)

    assert result.contributions[0].contribution == 0.123456789 * 0.30 * 100
    assert result.score == result.contributions[0].contribution
    assert serialized == {
        "config_version": "risk-v1",
        "score": round(result.score, 6),
        "factors": [
            {
                "name": item.name,
                "raw": round(item.normalized_value, 6),
                "normalized_value": round(item.normalized_value, 6),
                "weight": round(item.weight, 6),
                "contribution": round(item.contribution, 6),
            }
            for item in result.contributions
        ],
    }


def test_risk_config_serializer_persists_every_registered_parameter() -> None:
    assert serialize_risk_config(default_risk_config()) == {
        "algorithm_version": "risk-v1",
        "weights": {
            "proximity": 0.3,
            "population": 0.25,
            "critical_facilities": 0.2,
            "wind_alignment": 0.15,
            "detection_confidence": 0.05,
            "source_freshness": 0.05,
        },
        "population_saturation": 10_000.0,
        "critical_facility_saturation_count": 5.0,
        "wind_speed_saturation_mps": 15.0,
        "fire_freshness_seconds": 21_600.0,
        "weather_freshness_seconds": 3_600.0,
        "weather_search_radius_meters": 100_000.0,
    }


def test_risk_config_requires_version_and_positive_finite_thresholds() -> None:
    with pytest.raises(ValueError, match="algorithm_version"):
        replace(default_risk_config(), algorithm_version=" ")
    for field in (
        "population_saturation",
        "critical_facility_saturation_count",
        "wind_speed_saturation_mps",
        "fire_freshness_seconds",
        "weather_freshness_seconds",
        "weather_search_radius_meters",
    ):
        with pytest.raises(ValueError, match=field):
            replace(default_risk_config(), **{field: 0})


def test_contribution_and_breakdown_are_strict_frozen_values() -> None:
    result = score_risk(RiskFactors(1, 0, 0, 0, 0, 0), default_risk_config())

    with pytest.raises(FrozenInstanceError):
        result.score = 0  # type: ignore[misc]
    with pytest.raises(ValueError, match="name"):
        RiskContribution("unknown", 0, 0, 0, 0)
    with pytest.raises(ValueError, match="normalized_value"):
        RiskContribution("proximity", 0, nan, 0, 0)
    with pytest.raises(ValueError, match="contributions.*tuple"):
        RiskBreakdown(
            score=result.score,
            algorithm_version="risk-v1",
            contributions=list(result.contributions),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="factor order"):
        RiskBreakdown(
            score=result.score,
            algorithm_version="risk-v1",
            contributions=tuple(reversed(result.contributions)),
        )
    with pytest.raises(ValueError, match="sum"):
        replace(result, score=result.score + 1)
