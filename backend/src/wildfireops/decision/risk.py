"""Explainable portfolio risk heuristics.

The score in this module is a deterministic product heuristic.  It is not a
scientific probability, fire-spread prediction, or official severity rating.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from math import cos, isfinite, radians
from types import MappingProxyType

from pyproj import Geod

from wildfireops.domain.observations import (
    FrozenJsonObject,
    NormalizedObservation,
    WeatherObservation,
    freeze_json_object,
)
from wildfireops.geospatial.exposure import (
    ExposedAssetExposure,
    validate_buffer_meters,
)


FACTOR_NAMES = (
    "proximity",
    "population",
    "critical_facilities",
    "wind_alignment",
    "detection_confidence",
    "source_freshness",
)
CRITICAL_FACILITY_KINDS = frozenset({"hospital", "fire_station", "shelter"})
_WGS84 = Geod(ellps="WGS84")
_WEIGHT_FIELDS = (
    "proximity_weight",
    "population_weight",
    "critical_facilities_weight",
    "wind_alignment_weight",
    "detection_confidence_weight",
    "source_freshness_weight",
)
_THRESHOLD_FIELDS = (
    "population_saturation",
    "critical_facility_saturation_count",
    "wind_speed_saturation_mps",
    "fire_freshness_seconds",
    "weather_freshness_seconds",
    "weather_search_radius_meters",
)
_REGISTERED_RISK_PARAMETERS: Mapping[str, tuple[float, ...]] = MappingProxyType(
    {
        "risk-v1": (
            0.30,
            0.25,
            0.20,
            0.15,
            0.05,
            0.05,
            10_000.0,
            5.0,
            15.0,
            21_600.0,
            3_600.0,
            100_000.0,
        )
    }
)


@dataclass(frozen=True, slots=True)
class RiskFactors:
    proximity: float
    population: float
    critical_facilities: float
    wind_alignment: float
    detection_confidence: float
    source_freshness: float

    def __post_init__(self) -> None:
        for name in FACTOR_NAMES:
            object.__setattr__(self, name, _unit_interval(getattr(self, name), name))

    def ordered_values(self) -> tuple[float, ...]:
        return tuple(getattr(self, name) for name in FACTOR_NAMES)


@dataclass(frozen=True, slots=True)
class RiskConfig:
    algorithm_version: str = "risk-v1"
    proximity_weight: float = 0.30
    population_weight: float = 0.25
    critical_facilities_weight: float = 0.20
    wind_alignment_weight: float = 0.15
    detection_confidence_weight: float = 0.05
    source_freshness_weight: float = 0.05
    population_saturation: float = 10_000.0
    critical_facility_saturation_count: float = 5.0
    wind_speed_saturation_mps: float = 15.0
    fire_freshness_seconds: float = 21_600.0
    weather_freshness_seconds: float = 3_600.0
    weather_search_radius_meters: float = 100_000.0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.algorithm_version, str)
            or not self.algorithm_version.strip()
        ):
            raise ValueError("algorithm_version must be a nonblank string")
        object.__setattr__(self, "algorithm_version", self.algorithm_version.strip())

        for field in _WEIGHT_FIELDS:
            object.__setattr__(
                self,
                field,
                _finite_nonnegative(getattr(self, field), field),
            )
        decimal_total = sum(
            (Decimal(str(getattr(self, field))) for field in _WEIGHT_FIELDS),
            start=Decimal(0),
        )
        if abs(decimal_total - Decimal(1)) > Decimal("1e-9"):
            raise ValueError("risk weights must sum to 1 within 1e-9")

        for field in _THRESHOLD_FIELDS:
            object.__setattr__(
                self,
                field,
                _finite_positive(getattr(self, field), field),
            )

        registered = _REGISTERED_RISK_PARAMETERS.get(self.algorithm_version)
        if registered is None:
            raise ValueError(
                f"unknown risk algorithm version: {self.algorithm_version}"
            )
        configured = tuple(
            getattr(self, field) for field in (*_WEIGHT_FIELDS, *_THRESHOLD_FIELDS)
        )
        if configured != registered:
            raise ValueError(
                f"{self.algorithm_version} must use its registered parameters"
            )

    def ordered_weights(self) -> tuple[float, ...]:
        return (
            self.proximity_weight,
            self.population_weight,
            self.critical_facilities_weight,
            self.wind_alignment_weight,
            self.detection_confidence_weight,
            self.source_freshness_weight,
        )


@dataclass(frozen=True, slots=True)
class RiskContribution:
    name: str
    raw_value: float
    normalized_value: float
    weight: float
    contribution: float

    def __post_init__(self) -> None:
        if self.name not in FACTOR_NAMES:
            raise ValueError("contribution name must be a known risk factor")
        object.__setattr__(
            self, "raw_value", _unit_interval(self.raw_value, "raw_value")
        )
        object.__setattr__(
            self,
            "normalized_value",
            _unit_interval(self.normalized_value, "normalized_value"),
        )
        object.__setattr__(
            self,
            "weight",
            _finite_nonnegative(self.weight, "contribution weight"),
        )
        object.__setattr__(
            self,
            "contribution",
            _finite_nonnegative(self.contribution, "contribution"),
        )


@dataclass(frozen=True, slots=True)
class RiskBreakdown:
    score: float
    algorithm_version: str
    contributions: tuple[RiskContribution, ...]

    def __post_init__(self) -> None:
        score = _finite_number(self.score, "score")
        if not 0.0 <= score <= 100.0 + 1e-6:
            raise ValueError("score must be within the normalized 0-to-100 range")
        object.__setattr__(self, "score", score)
        if (
            not isinstance(self.algorithm_version, str)
            or not self.algorithm_version.strip()
        ):
            raise ValueError("algorithm_version must be a nonblank string")
        object.__setattr__(self, "algorithm_version", self.algorithm_version.strip())
        if not isinstance(self.contributions, tuple):
            raise ValueError("contributions must be a tuple")
        if tuple(item.name for item in self.contributions) != FACTOR_NAMES:
            raise ValueError("contributions must use the canonical factor order")
        if abs(sum(item.contribution for item in self.contributions) - score) > 1e-9:
            raise ValueError("contribution sum must equal score")


@dataclass(frozen=True, slots=True)
class NormalizedRiskInputs:
    factors: RiskFactors
    raw_evidence: FrozenJsonObject
    selected_weather_identity: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_evidence", freeze_json_object(self.raw_evidence))


def default_risk_config() -> RiskConfig:
    return RiskConfig()


def score_risk(factors: RiskFactors, config: RiskConfig) -> RiskBreakdown:
    contributions = tuple(
        RiskContribution(
            name=name,
            raw_value=value,
            normalized_value=value,
            weight=weight,
            contribution=value * weight * 100.0,
        )
        for name, value, weight in zip(
            FACTOR_NAMES,
            factors.ordered_values(),
            config.ordered_weights(),
            strict=True,
        )
    )
    return RiskBreakdown(
        score=sum(item.contribution for item in contributions),
        algorithm_version=config.algorithm_version,
        contributions=contributions,
    )


def normalize_risk_inputs(
    *,
    exposures: Sequence[ExposedAssetExposure],
    detections: Sequence[NormalizedObservation],
    weather_observations: Sequence[WeatherObservation],
    incident_longitude: float,
    incident_latitude: float,
    reference_at: datetime,
    exposure_buffer_meters: float,
    config: RiskConfig,
) -> NormalizedRiskInputs:
    """Normalize sourced evidence into conservative, explainable heuristics.

    All factors are clamped to ``[0, 1]``. Missing weather contributes zero to
    both wind and source freshness; this deliberately avoids treating missing
    evidence as reassuring. The result remains a portfolio heuristic, not a
    scientific fire-spread model.
    """
    if not isinstance(reference_at, datetime) or reference_at.utcoffset() != timedelta(
        0
    ):
        raise ValueError("reference_at must be UTC")
    longitude = _coordinate(incident_longitude, "incident_longitude", -180, 180)
    latitude = _coordinate(incident_latitude, "incident_latitude", -90, 90)
    buffer_meters = validate_buffer_meters(exposure_buffer_meters)

    current_detections = tuple(
        detection for detection in detections if detection.observed_at <= reference_at
    )
    if not current_detections:
        raise ValueError("active incident requires at least one nonfuture detection")

    nearest_distance = (
        min(exposure.distance_meters for exposure in exposures) if exposures else None
    )
    proximity = (
        0.0
        if nearest_distance is None
        else _clamp(1.0 - nearest_distance / buffer_meters)
    )

    communities = tuple(
        exposure for exposure in exposures if exposure.asset_kind == "community"
    )
    for community in communities:
        if community.population is None or community.population < 0:
            raise ValueError(
                f"community {community.asset_id} population must be nonnegative"
            )
    exposed_population = sum(community.population or 0 for community in communities)
    population = (
        1.0
        if exposed_population >= config.population_saturation
        else exposed_population / config.population_saturation
    )

    critical = tuple(
        exposure
        for exposure in exposures
        if exposure.asset_kind in CRITICAL_FACILITY_KINDS
    )
    critical_kinds = tuple(sorted({item.asset_kind for item in critical}))
    critical_facilities = _clamp(
        len(critical) / config.critical_facility_saturation_count
    )

    confidence_mean = sum(
        detection.confidence for detection in current_detections
    ) / len(current_detections)

    selected_weather = _select_weather(
        weather_observations,
        reference_at=reference_at,
        incident_longitude=longitude,
        incident_latitude=latitude,
        radius_meters=config.weather_search_radius_meters,
    )
    max_alignment: float | None = None
    spread_bearing = (
        None
        if selected_weather is None
        else (selected_weather.wind_direction_degrees + 180.0) % 360.0
    )
    if selected_weather is None or not exposures:
        wind_alignment = 0.0
    else:
        assert spread_bearing is not None
        alignments = tuple(
            1.0
            if exposure.bearing_degrees is None
            else _direction_alignment(spread_bearing, exposure.bearing_degrees)
            for exposure in exposures
        )
        max_alignment = max(alignments)
        wind_alignment = _clamp(
            max_alignment
            * min(
                selected_weather.wind_speed_mps / config.wind_speed_saturation_mps,
                1.0,
            )
        )

    latest_fire_at = max(detection.observed_at for detection in current_detections)
    fire_age = (reference_at - latest_fire_at).total_seconds()
    weather_age = (
        None
        if selected_weather is None
        else (reference_at - selected_weather.observed_at).total_seconds()
    )
    fire_freshness = _freshness(fire_age, config.fire_freshness_seconds)
    weather_freshness = (
        0.0
        if weather_age is None
        else _freshness(weather_age, config.weather_freshness_seconds)
    )
    source_freshness = min(fire_freshness, weather_freshness)

    factors = RiskFactors(
        proximity=proximity,
        population=population,
        critical_facilities=critical_facilities,
        wind_alignment=wind_alignment,
        detection_confidence=confidence_mean,
        source_freshness=source_freshness,
    )
    raw_evidence = freeze_json_object(
        {
            "proximity": {
                "nearest_distance": nearest_distance,
                "buffer": buffer_meters,
            },
            "population": {
                "population": exposed_population,
                "community_count": len(communities),
                "saturation_population": config.population_saturation,
            },
            "critical_facilities": {
                "count": len(critical),
                "kinds": critical_kinds,
                "saturation_count": config.critical_facility_saturation_count,
            },
            "wind_alignment": {
                "weather_identity": (
                    None if selected_weather is None else selected_weather.identity
                ),
                "speed": (
                    None
                    if selected_weather is None
                    else selected_weather.wind_speed_mps
                ),
                "from": (
                    None
                    if selected_weather is None
                    else selected_weather.wind_direction_degrees
                ),
                "spread": spread_bearing,
                "max_alignment": max_alignment,
                "saturation_speed": config.wind_speed_saturation_mps,
            },
            "detection_confidence": {
                "mean": confidence_mean,
                "detection_count": len(current_detections),
            },
            "source_freshness": {
                "fire_age": fire_age,
                "weather_age": weather_age,
                "stale_thresholds": {
                    "fire_seconds": config.fire_freshness_seconds,
                    "weather_seconds": config.weather_freshness_seconds,
                },
            },
        }
    )
    return NormalizedRiskInputs(
        factors=factors,
        raw_evidence=raw_evidence,
        selected_weather_identity=(
            None if selected_weather is None else selected_weather.identity
        ),
    )


def serialize_risk_breakdown(
    breakdown: RiskBreakdown,
    raw_evidence: Mapping[str, object] | None = None,
    *,
    digits: int = 6,
) -> dict[str, object]:
    """Serialize one risk result; calculated values are rounded only here."""
    factors: list[dict[str, object]] = []
    for item in breakdown.contributions:
        raw = (
            raw_evidence[item.name]
            if raw_evidence is not None and item.name in raw_evidence
            else item.raw_value
        )
        factors.append(
            {
                "name": item.name,
                "raw": _canonical_json(raw, digits=digits),
                "normalized_value": round(item.normalized_value, digits),
                "weight": round(item.weight, digits),
                "contribution": round(item.contribution, digits),
            }
        )
    return {
        "config_version": breakdown.algorithm_version,
        "score": round(breakdown.score, digits),
        "factors": factors,
    }


def serialize_risk_config(
    config: RiskConfig,
    *,
    digits: int = 6,
) -> dict[str, object]:
    """Serialize the complete parameter set bound to a risk algorithm version."""
    return {
        "algorithm_version": config.algorithm_version,
        "weights": {
            name: round(weight, digits)
            for name, weight in zip(
                FACTOR_NAMES,
                config.ordered_weights(),
                strict=True,
            )
        },
        **{field: round(getattr(config, field), digits) for field in _THRESHOLD_FIELDS},
    }


def _canonical_json(value: object, *, digits: int) -> object:
    if isinstance(value, Mapping):
        return {
            key: _canonical_json(value[key], digits=digits) for key in sorted(value)
        }
    if isinstance(value, tuple | list):
        return [_canonical_json(item, digits=digits) for item in value]
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("risk evidence contains a non-finite number")
        return round(value, digits)
    if value is None or isinstance(value, bool | int | str):
        return value
    raise ValueError(f"risk evidence contains unsupported type: {type(value).__name__}")


def _select_weather(
    observations: Sequence[WeatherObservation],
    *,
    reference_at: datetime,
    incident_longitude: float,
    incident_latitude: float,
    radius_meters: float,
) -> WeatherObservation | None:
    candidates: list[tuple[WeatherObservation, float]] = []
    for observation in observations:
        if observation.observed_at > reference_at:
            continue
        _, _, distance = _WGS84.inv(
            incident_longitude,
            incident_latitude,
            observation.longitude,
            observation.latitude,
        )
        if not isfinite(distance):
            raise ValueError("weather distance must be finite")
        if distance <= radius_meters:
            candidates.append((observation, distance))
    if not candidates:
        return None
    latest_observed_at = max(item[0].observed_at for item in candidates)
    return min(
        (item for item in candidates if item[0].observed_at == latest_observed_at),
        key=lambda item: (
            item[1],
            item[0].identity,
        ),
    )[0]


def _direction_alignment(spread_bearing: float, asset_bearing: float) -> float:
    shortest_angle = (asset_bearing - spread_bearing + 180.0) % 360.0 - 180.0
    return _clamp((1.0 + cos(radians(shortest_angle))) / 2.0)


def _freshness(age_seconds: float, threshold_seconds: float) -> float:
    return _clamp(1.0 - age_seconds / threshold_seconds)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _coordinate(value: object, field: str, lower: float, upper: float) -> float:
    parsed = _finite_number(value, field)
    if not lower <= parsed <= upper:
        raise ValueError(f"{field} is outside valid range")
    return parsed


def _unit_interval(value: object, field: str) -> float:
    parsed = _finite_number(value, field)
    if not 0.0 <= parsed <= 1.0:
        raise ValueError(f"{field} must be between 0 and 1")
    return parsed


def _finite_positive(value: object, field: str) -> float:
    parsed = _finite_number(value, field)
    if parsed <= 0:
        raise ValueError(f"{field} must be a finite positive number")
    return parsed


def _finite_nonnegative(value: object, field: str) -> float:
    parsed = _finite_number(value, field)
    if parsed < 0:
        raise ValueError(f"{field} weight must be finite and nonnegative")
    return parsed


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    try:
        parsed = float(value)
    except (OverflowError, ValueError):
        raise ValueError(f"{field} must be a finite number") from None
    if not isfinite(parsed):
        raise ValueError(f"{field} must be a finite number")
    return parsed
