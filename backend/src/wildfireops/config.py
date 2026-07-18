from functools import lru_cache
from math import isfinite
from pathlib import Path

from pydantic import (
    AnyHttpUrl,
    SecretStr,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


_HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


class Settings(BaseSettings):
    app_name: str = "wildfireops-api"
    environment: str = "development"
    database_url: str = (
        "postgresql+asyncpg://wildfireops:wildfireops@localhost:5432/wildfireops"
    )
    replay_package: Path | None = None
    firms_map_key: SecretStr | None = None
    firms_area_url: str = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
    firms_bbox: str = "-122.40,39.20,-120.30,41.00"
    firms_source: str = "VIIRS_SNPP_NRT"
    firms_day_range: int = 1
    firms_poll_interval_seconds: float = 300.0
    nws_user_agent: str = (
        "WildfireOps/0.1 (portfolio simulation; contact: wildfireops@example.invalid)"
    )
    nws_observation_url: str = (
        "https://api.weather.gov/stations/KCIC/observations/latest"
    )
    nws_poll_interval_seconds: float = 300.0
    clustering_spatial_radius_meters: float = 5_000.0
    clustering_temporal_window_seconds: float = 21_600.0
    clustering_minimum_points: int = 2
    clustering_algorithm_version: str = "spatiotemporal-dbscan-v1"
    exposure_buffer_meters: float = 10_000.0
    risk_algorithm_version: str = "risk-v1"
    risk_proximity_weight: float = 0.30
    risk_population_weight: float = 0.25
    risk_critical_facilities_weight: float = 0.20
    risk_wind_alignment_weight: float = 0.15
    risk_detection_confidence_weight: float = 0.05
    risk_source_freshness_weight: float = 0.05
    risk_population_saturation: float = 10_000.0
    risk_critical_facility_saturation_count: float = 5.0
    risk_wind_speed_saturation_mps: float = 15.0
    risk_fire_freshness_seconds: float = 21_600.0
    risk_weather_freshness_seconds: float = 3_600.0
    risk_weather_search_radius_meters: float = 100_000.0
    model_config = SettingsConfigDict(env_file=".env", env_prefix="WILDFIREOPS_")

    @field_validator("firms_map_key", mode="before")
    @classmethod
    def normalize_blank_firms_key(cls, value: object) -> object:
        if isinstance(value, SecretStr):
            return None if not value.get_secret_value().strip() else value
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "firms_source",
        "clustering_algorithm_version",
        "risk_algorithm_version",
    )
    @classmethod
    def validate_nonblank_setting(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("setting must not be blank")
        return normalized

    @field_validator("firms_area_url", "nws_observation_url", mode="before")
    @classmethod
    def validate_live_source_url(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("live source URL must be an absolute HTTP(S) URL")
        try:
            parsed = _HTTP_URL_ADAPTER.validate_python(value.strip())
        except ValidationError:
            raise ValueError(
                "live source URL must be an absolute HTTP(S) URL"
            ) from None
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("live source URL must not contain credentials")
        return str(parsed)

    @field_validator("nws_user_agent")
    @classmethod
    def validate_nws_user_agent(cls, value: str) -> str:
        user_agent = value.strip()
        if not user_agent:
            raise ValueError("NWS user agent must not be blank")
        return user_agent

    @field_validator("firms_bbox")
    @classmethod
    def validate_firms_bbox(cls, value: str) -> str:
        parts = value.split(",")
        if len(parts) != 4:
            raise ValueError("FIRMS bbox must contain four coordinates")
        try:
            west, south, east, north = (float(part) for part in parts)
        except (OverflowError, ValueError):
            raise ValueError("FIRMS bbox coordinates must be finite") from None
        if not all(isfinite(item) for item in (west, south, east, north)):
            raise ValueError("FIRMS bbox coordinates must be finite")
        if not -180 <= west < east <= 180 or not -90 <= south < north <= 90:
            raise ValueError("FIRMS bbox must be an ordered WGS84 bounding box")
        return ",".join(part.strip() for part in parts)

    @field_validator(
        "firms_poll_interval_seconds",
        "nws_poll_interval_seconds",
        mode="before",
    )
    @classmethod
    def validate_poll_interval(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError("poll interval must be a finite positive number")
        try:
            parsed = float(value)
        except (OverflowError, ValueError):
            raise ValueError("poll interval must be a finite positive number") from None
        if not isfinite(parsed) or parsed <= 0:
            raise ValueError("poll interval must be a finite positive number")
        return value

    @field_validator("firms_day_range", mode="before")
    @classmethod
    def validate_firms_day_range(cls, value: object) -> object:
        if isinstance(value, bool) or not _is_positive_integer_input(value):
            raise ValueError("FIRMS day range must be an integer from 1 to 5")
        if not isinstance(value, (int, str)) or int(value) > 5:
            raise ValueError("FIRMS day range must be an integer from 1 to 5")
        return value

    @field_validator(
        "clustering_spatial_radius_meters",
        "clustering_temporal_window_seconds",
        mode="before",
    )
    @classmethod
    def validate_clustering_number(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError("clustering value must be a finite positive number")
        try:
            parsed = float(value)
        except (OverflowError, ValueError):
            raise ValueError(
                "clustering value must be a finite positive number"
            ) from None
        if not isfinite(parsed) or parsed <= 0:
            raise ValueError("clustering value must be a finite positive number")
        return value

    @field_validator("clustering_minimum_points", mode="before")
    @classmethod
    def validate_clustering_minimum_points(cls, value: object) -> object:
        if isinstance(value, bool) or not _is_positive_integer_input(value):
            raise ValueError("clustering minimum points must be a positive integer")
        return value

    @field_validator("exposure_buffer_meters", mode="before")
    @classmethod
    def validate_exposure_buffer(cls, value: object) -> object:
        parsed = _parse_finite_number(value, "exposure buffer")
        if not 100 <= parsed <= 100_000:
            raise ValueError(
                "exposure buffer must be between 100 and 100000 meters inclusive"
            )
        return value

    @field_validator(
        "risk_proximity_weight",
        "risk_population_weight",
        "risk_critical_facilities_weight",
        "risk_wind_alignment_weight",
        "risk_detection_confidence_weight",
        "risk_source_freshness_weight",
        mode="before",
    )
    @classmethod
    def validate_risk_weight(cls, value: object) -> object:
        parsed = _parse_finite_number(value, "risk weight")
        if parsed < 0:
            raise ValueError("risk weight must be finite and nonnegative")
        return value

    @field_validator(
        "risk_population_saturation",
        "risk_critical_facility_saturation_count",
        "risk_wind_speed_saturation_mps",
        "risk_fire_freshness_seconds",
        "risk_weather_freshness_seconds",
        "risk_weather_search_radius_meters",
        mode="before",
    )
    @classmethod
    def validate_risk_threshold(cls, value: object) -> object:
        parsed = _parse_finite_number(value, "risk threshold")
        if parsed <= 0:
            raise ValueError("risk threshold must be a finite positive number")
        return value

    @model_validator(mode="after")
    def validate_risk_version_contract(self) -> "Settings":
        from wildfireops.decision.risk import RiskConfig

        RiskConfig(
            algorithm_version=self.risk_algorithm_version,
            proximity_weight=self.risk_proximity_weight,
            population_weight=self.risk_population_weight,
            critical_facilities_weight=self.risk_critical_facilities_weight,
            wind_alignment_weight=self.risk_wind_alignment_weight,
            detection_confidence_weight=self.risk_detection_confidence_weight,
            source_freshness_weight=self.risk_source_freshness_weight,
            population_saturation=self.risk_population_saturation,
            critical_facility_saturation_count=(
                self.risk_critical_facility_saturation_count
            ),
            wind_speed_saturation_mps=self.risk_wind_speed_saturation_mps,
            fire_freshness_seconds=self.risk_fire_freshness_seconds,
            weather_freshness_seconds=self.risk_weather_freshness_seconds,
            weather_search_radius_meters=self.risk_weather_search_radius_meters,
        )
        return self


def _is_positive_integer_input(value: object) -> bool:
    if isinstance(value, int):
        return value > 0
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or not stripped.isascii():
            return False
        try:
            return int(stripped) > 0 and str(int(stripped)) == stripped
        except ValueError:
            return False
    return False


def _parse_finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{field} must be a finite number")
    try:
        parsed = float(value)
    except (OverflowError, ValueError):
        raise ValueError(f"{field} must be a finite number") from None
    if not isfinite(parsed):
        raise ValueError(f"{field} must be a finite number")
    return parsed


@lru_cache
def get_settings() -> Settings:
    return Settings()
