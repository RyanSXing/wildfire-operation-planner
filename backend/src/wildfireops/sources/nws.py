import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from math import isfinite
from typing import Any

import httpx

from wildfireops.domain.observations import (
    FrozenJsonObject,
    WeatherObservation,
    freeze_json_object,
)
from wildfireops.sources.base import SourceBatch, SourceValidationFailure
from wildfireops.sources.http import (
    RetryPolicy,
    Sleep,
    fetch_with_retry,
)


class NwsAdapter:
    def __init__(
        self,
        client: httpx.AsyncClient,
        request: httpx.Request,
        user_agent: str,
        *,
        policy: RetryPolicy = RetryPolicy(),
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("NWS user agent must not be blank")
        self._client = client
        self._request = _with_user_agent(request, user_agent)
        self._policy = policy
        self._sleep = sleep

    @property
    def source_name(self) -> str:
        return "nws"

    async def fetch(self) -> SourceBatch:
        response = await fetch_with_retry(
            self._client,
            self._request,
            self._policy,
            sleep=self._sleep,
            source_name=self.source_name,
        )
        raw_payload = freeze_json_object({"response_body": response.text})
        try:
            payload: Any = response.json(
                parse_constant=_reject_non_finite_json_constant,
                parse_float=_finite_json_float,
            )
        except (UnicodeDecodeError, ValueError):
            return self._failure(
                "response body is not valid JSON",
                raw_payload,
            )
        if not isinstance(payload, Mapping):
            return self._failure(
                "payload must be an object",
                raw_payload,
            )

        try:
            payload_object = _string_keyed_object(payload, "payload")
            properties = _string_keyed_object(
                payload_object.get("properties"),
                "properties",
            )
            raw_payload = freeze_json_object(properties)
            observation = self._normalize(payload_object, raw_payload)
        except (KeyError, TypeError, ValueError) as error:
            return self._failure(str(error), raw_payload)

        return SourceBatch((observation,), ())

    def _normalize(
        self,
        payload: Mapping[str, object],
        properties: FrozenJsonObject,
    ) -> WeatherObservation:
        observed_at = _timestamp(properties)
        longitude, latitude = _coordinates(payload)
        wind_speed_mps = _wind_speed(properties)
        wind_direction_degrees = _measurement(
            properties,
            "windDirection",
            "wmoUnit:degree_(angle)",
        )
        temperature_celsius = _optional_measurement(
            properties,
            "temperature",
            "wmoUnit:degC",
        )
        identity = "|".join(
            (
                observed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                f"{latitude:.5f}",
                f"{longitude:.5f}",
            )
        )

        return WeatherObservation(
            source_name=self.source_name,
            source_record_id=sha256(identity.encode("utf-8")).hexdigest(),
            observed_at=observed_at,
            longitude=longitude,
            latitude=latitude,
            wind_speed_mps=wind_speed_mps,
            wind_direction_degrees=wind_direction_degrees,
            temperature_celsius=temperature_celsius,
            raw_payload=properties,
        )

    def _failure(
        self,
        reason: str,
        raw_payload: FrozenJsonObject,
    ) -> SourceBatch:
        return SourceBatch(
            (),
            (
                SourceValidationFailure(
                    source_name=self.source_name,
                    reason=f"invalid NWS observation: {reason}",
                    raw_payload=raw_payload,
                ),
            ),
        )


def _with_user_agent(request: httpx.Request, user_agent: str) -> httpx.Request:
    headers = request.headers.copy()
    headers["User-Agent"] = user_agent
    return httpx.Request(
        request.method,
        request.url,
        headers=headers,
        content=request.content,
        extensions=dict(request.extensions),
    )


def _string_keyed_object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    object_value: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{field} keys must be strings")
        object_value[key] = item
    return object_value


def _timestamp(properties: Mapping[str, object]) -> datetime:
    value = properties.get("timestamp")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp is missing")
    try:
        observed_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("timestamp is invalid") from None
    if observed_at.utcoffset() is None:
        raise ValueError("timestamp must include an offset")
    return observed_at.astimezone(UTC)


def _coordinates(payload: Mapping[str, object]) -> tuple[float, float]:
    geometry = payload.get("geometry")
    if not isinstance(geometry, Mapping) or geometry.get("type") != "Point":
        raise ValueError("geometry must be a Point")
    coordinates = geometry.get("coordinates")
    if (
        not isinstance(coordinates, Sequence)
        or isinstance(coordinates, (str, bytes, bytearray))
        or len(coordinates) < 2
    ):
        raise ValueError("geometry coordinates are invalid")
    return _coordinate_value(coordinates[0]), _coordinate_value(coordinates[1])


def _coordinate_value(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("geometry coordinates are invalid")
    try:
        coordinate = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("geometry coordinates are invalid") from None
    if not isfinite(coordinate):
        raise ValueError("geometry coordinates are invalid")
    return coordinate


def _wind_speed(properties: Mapping[str, object]) -> float:
    measurement = _measurement_object(properties, "windSpeed")
    value = _measurement_value(measurement, "windSpeed")
    unit = measurement.get("unitCode")
    if unit == "wmoUnit:km_h-1":
        return value / 3.6
    if unit == "wmoUnit:m_s-1":
        return value
    raise ValueError("windSpeed unit is unsupported")


def _measurement(
    properties: Mapping[str, object],
    field: str,
    unit: str,
) -> float:
    measurement = _measurement_object(properties, field)
    value = _measurement_value(measurement, field)
    if measurement.get("unitCode") != unit:
        raise ValueError(f"{field} unit is unsupported")
    return value


def _optional_measurement(
    properties: Mapping[str, object],
    field: str,
    unit: str,
) -> float | None:
    measurement = properties.get(field)
    if measurement is None:
        return None
    if not isinstance(measurement, Mapping):
        raise ValueError(f"{field} is invalid")
    if measurement.get("value") is None:
        return None
    value = _measurement_value(measurement, field)
    if measurement.get("unitCode") != unit:
        raise ValueError(f"{field} unit is unsupported")
    return value


def _measurement_object(
    properties: Mapping[str, object],
    field: str,
) -> Mapping[str, object]:
    measurement = properties.get(field)
    if measurement is None:
        raise ValueError(f"{field} is missing")
    if not isinstance(measurement, Mapping):
        raise ValueError(f"{field} is invalid")
    return measurement


def _measurement_value(
    measurement: Mapping[str, object],
    field: str,
) -> float:
    value = measurement.get("value")
    if value is None:
        raise ValueError(f"{field} is missing")
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{field} is invalid")
    try:
        number = float(value)
    except OverflowError:
        raise ValueError(f"{field} must be finite") from None
    except (TypeError, ValueError):
        raise ValueError(f"{field} is invalid") from None
    if not isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _reject_non_finite_json_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _finite_json_float(value: str) -> float:
    number = float(value)
    if not isfinite(number):
        raise ValueError("non-finite JSON number is not allowed")
    return number
