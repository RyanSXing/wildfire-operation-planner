import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from wildfireops.domain.observations import WeatherObservation
from wildfireops.sources.http import RetryPolicy
from wildfireops.sources.nws import NwsAdapter


FIXTURES = Path(__file__).parents[2] / "fixtures"
REQUEST_URL = "https://sources.invalid/nws-observation"
USER_AGENT = "WildfireOps portfolio@example.invalid"


async def no_sleep(_: float) -> None:
    pass


def json_transport(
    payload: dict[str, Any],
    sent_requests: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if sent_requests is not None:
            sent_requests.append(request)
        return httpx.Response(200, json=payload, request=request)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_nws_adapter_normalizes_observation_and_preserves_properties() -> None:
    payload = json.loads((FIXTURES / "nws_observation.json").read_text())

    async with httpx.AsyncClient(transport=json_transport(payload)) as client:
        batch = await NwsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            USER_AGENT,
        ).fetch()

    assert batch.failures == ()
    assert len(batch.observations) == 1
    observation = batch.observations[0]
    assert isinstance(observation, WeatherObservation)
    assert observation.observed_at == datetime(2024, 7, 24, 18, 20, tzinfo=UTC)
    assert observation.longitude == -121.612
    assert observation.latitude == 39.805
    assert observation.wind_speed_mps == pytest.approx(5.0)
    assert observation.wind_direction_degrees == 270.0
    assert observation.temperature_celsius == 34.0
    assert observation.raw_payload == payload["properties"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("coordinate_index", "invalid_coordinate"),
    [
        (0, True),
        (1, False),
        (0, "NaN"),
        (1, "Infinity"),
        (0, "-Infinity"),
        (1, "1e309"),
        (0, "-1e309"),
        (1, 10**400),
    ],
)
async def test_nws_adapter_quarantines_invalid_coordinate_numbers(
    coordinate_index: int,
    invalid_coordinate: Any,
) -> None:
    payload = json.loads((FIXTURES / "nws_observation.json").read_text())
    payload["geometry"]["coordinates"][coordinate_index] = invalid_coordinate

    async with httpx.AsyncClient(transport=json_transport(payload)) as client:
        batch = await NwsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            USER_AGENT,
            sleep=no_sleep,
        ).fetch()

    assert batch.observations == ()
    assert len(batch.failures) == 1
    failure = batch.failures[0]
    assert failure.reason == (
        "invalid NWS observation: geometry coordinates are invalid"
    )
    assert failure.raw_payload == payload["properties"]


@pytest.mark.asyncio
async def test_nws_adapter_accepts_finite_numeric_string_coordinates() -> None:
    payload = json.loads((FIXTURES / "nws_observation.json").read_text())
    payload["geometry"]["coordinates"] = ["-121.612", "39.805"]

    async with httpx.AsyncClient(transport=json_transport(payload)) as client:
        batch = await NwsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            USER_AGENT,
            sleep=no_sleep,
        ).fetch()

    assert batch.failures == ()
    observation = batch.observations[0]
    assert isinstance(observation, WeatherObservation)
    assert observation.longitude == -121.612
    assert observation.latitude == 39.805


@pytest.mark.asyncio
async def test_nws_adapter_preserves_missing_optional_temperature() -> None:
    payload = json.loads((FIXTURES / "nws_observation.json").read_text())
    payload["properties"]["temperature"]["value"] = None

    async with httpx.AsyncClient(transport=json_transport(payload)) as client:
        batch = await NwsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            USER_AGENT,
            sleep=no_sleep,
        ).fetch()

    assert batch.failures == ()
    observation = batch.observations[0]
    assert isinstance(observation, WeatherObservation)
    assert observation.temperature_celsius is None


@pytest.mark.asyncio
async def test_nws_adapter_accepts_wind_speed_already_in_metres_per_second() -> None:
    payload = json.loads((FIXTURES / "nws_observation.json").read_text())
    payload["properties"]["windSpeed"] = {
        "unitCode": "wmoUnit:m_s-1",
        "value": 5.25,
    }

    async with httpx.AsyncClient(transport=json_transport(payload)) as client:
        batch = await NwsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            USER_AGENT,
            sleep=no_sleep,
        ).fetch()

    assert batch.failures == ()
    observation = batch.observations[0]
    assert isinstance(observation, WeatherObservation)
    assert observation.wind_speed_mps == 5.25


@pytest.mark.asyncio
async def test_nws_adapter_quarantines_unsupported_wind_speed_unit() -> None:
    payload = json.loads((FIXTURES / "nws_observation.json").read_text())
    payload["properties"]["windSpeed"]["unitCode"] = "wmoUnit:kn"

    async with httpx.AsyncClient(transport=json_transport(payload)) as client:
        batch = await NwsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            USER_AGENT,
            sleep=no_sleep,
        ).fetch()

    assert batch.observations == ()
    assert len(batch.failures) == 1
    assert batch.failures[0].reason == (
        "invalid NWS observation: windSpeed unit is unsupported"
    )
    assert batch.failures[0].raw_payload == payload["properties"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        ("2024-07-24T18:20:00Z", datetime(2024, 7, 24, 18, 20, tzinfo=UTC)),
        (
            "2024-07-24T11:20:00-07:00",
            datetime(2024, 7, 24, 18, 20, tzinfo=UTC),
        ),
    ],
)
async def test_nws_adapter_normalizes_offset_timestamps_to_utc(
    timestamp: str,
    expected: datetime,
) -> None:
    payload = json.loads((FIXTURES / "nws_observation.json").read_text())
    payload["properties"]["timestamp"] = timestamp

    async with httpx.AsyncClient(transport=json_transport(payload)) as client:
        batch = await NwsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            USER_AGENT,
            sleep=no_sleep,
        ).fetch()

    assert batch.failures == ()
    assert batch.observations[0].observed_at == expected


@pytest.mark.asyncio
async def test_nws_adapter_quarantines_naive_timestamp() -> None:
    payload = json.loads((FIXTURES / "nws_observation.json").read_text())
    payload["properties"]["timestamp"] = "2024-07-24T18:20:00"

    async with httpx.AsyncClient(transport=json_transport(payload)) as client:
        batch = await NwsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            USER_AGENT,
            sleep=no_sleep,
        ).fetch()

    assert batch.observations == ()
    assert len(batch.failures) == 1
    assert batch.failures[0].reason == (
        "invalid NWS observation: timestamp must include an offset"
    )
    assert batch.failures[0].raw_payload == payload["properties"]


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_measurement", ["windSpeed", "windDirection"])
async def test_nws_adapter_quarantines_missing_required_measurement(
    missing_measurement: str,
) -> None:
    payload = json.loads((FIXTURES / "nws_observation.json").read_text())
    payload["properties"][missing_measurement]["value"] = None

    async with httpx.AsyncClient(transport=json_transport(payload)) as client:
        batch = await NwsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            USER_AGENT,
            sleep=no_sleep,
        ).fetch()

    assert batch.observations == ()
    assert len(batch.failures) == 1
    assert batch.failures[0].source_name == "nws"
    assert batch.failures[0].reason == (
        f"invalid NWS observation: {missing_measurement} is missing"
    )
    assert batch.failures[0].raw_payload == payload["properties"]


@pytest.mark.asyncio
async def test_nws_adapter_sets_user_agent_without_mutating_request() -> None:
    payload = json.loads((FIXTURES / "nws_observation.json").read_text())
    sent_requests: list[httpx.Request] = []

    async with httpx.AsyncClient(
        transport=json_transport(payload, sent_requests)
    ) as client:
        request = client.build_request(
            "GET",
            REQUEST_URL,
            headers={"User-Agent": "caller-owned"},
        )
        await NwsAdapter(
            client,
            request,
            USER_AGENT,
            sleep=no_sleep,
        ).fetch()

    assert sent_requests[0].headers["User-Agent"] == USER_AGENT
    assert request.headers["User-Agent"] == "caller-owned"


@pytest.mark.asyncio
async def test_nws_adapter_rejects_blank_user_agent() -> None:
    async with httpx.AsyncClient() as client:
        request = client.build_request("GET", REQUEST_URL)
        with pytest.raises(ValueError, match="NWS user agent must not be blank"):
            NwsAdapter(client, request, "  ", sleep=no_sleep)


@pytest.mark.asyncio
async def test_nws_adapter_retries_transient_response_with_user_agent() -> None:
    payload = json.loads((FIXTURES / "nws_observation.json").read_text())
    attempts = 0
    user_agents: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        user_agents.append(request.headers["User-Agent"])
        if attempts == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, json=payload, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        batch = await NwsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            USER_AGENT,
            policy=RetryPolicy(max_attempts=2),
            sleep=no_sleep,
        ).fetch()

    assert attempts == 2
    assert user_agents == [USER_AGENT, USER_AGENT]
    assert len(batch.observations) == 1


@pytest.mark.asyncio
async def test_nws_adapter_quarantines_malformed_json_response() -> None:
    response_body = "not-json"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=response_body, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        batch = await NwsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            USER_AGENT,
            sleep=no_sleep,
        ).fetch()

    assert batch.observations == ()
    assert len(batch.failures) == 1
    assert batch.failures[0].reason == (
        "invalid NWS observation: response body is not valid JSON"
    )
    assert batch.failures[0].raw_payload == {"response_body": response_body}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "constant",
    ["NaN", "Infinity", "-Infinity", "1e309", "-1e309"],
)
async def test_nws_adapter_rejects_non_finite_numbers_during_json_decode(
    constant: str,
) -> None:
    response_body = (
        (FIXTURES / "nws_observation.json")
        .read_text()
        .replace(
            '"value": 18.0',
            f'"value": {constant}',
            1,
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=response_body, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        batch = await NwsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            USER_AGENT,
            sleep=no_sleep,
        ).fetch()

    assert batch.observations == ()
    assert len(batch.failures) == 1
    failure = batch.failures[0]
    assert failure.reason == (
        "invalid NWS observation: response body is not valid JSON"
    )
    assert failure.raw_payload == {"response_body": response_body}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        (field, value)
        for field in ("windSpeed", "windDirection", "temperature")
        for value in ("NaN", "Infinity", "-Infinity", "1e309", "-1e309")
    ],
)
async def test_nws_adapter_quarantines_non_finite_measurement_strings(
    field: str,
    value: str,
) -> None:
    payload = json.loads((FIXTURES / "nws_observation.json").read_text())
    payload["properties"][field]["value"] = value

    async with httpx.AsyncClient(transport=json_transport(payload)) as client:
        batch = await NwsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            USER_AGENT,
            sleep=no_sleep,
        ).fetch()

    assert batch.observations == ()
    assert len(batch.failures) == 1
    failure = batch.failures[0]
    assert failure.reason == f"invalid NWS observation: {field} must be finite"
    assert failure.raw_payload == payload["properties"]


@pytest.mark.asyncio
async def test_nws_adapter_quarantines_integer_measurement_too_large_for_float() -> (
    None
):
    payload = json.loads((FIXTURES / "nws_observation.json").read_text())
    payload["properties"]["temperature"]["value"] = 10**400

    async with httpx.AsyncClient(transport=json_transport(payload)) as client:
        batch = await NwsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            USER_AGENT,
            sleep=no_sleep,
        ).fetch()

    assert batch.observations == ()
    assert len(batch.failures) == 1
    failure = batch.failures[0]
    assert failure.reason == ("invalid NWS observation: temperature must be finite")
    assert failure.raw_payload == payload["properties"]


@pytest.mark.asyncio
@pytest.mark.parametrize("response_body", ["[]", "42", "null", '"scalar"'])
async def test_nws_adapter_preserves_body_for_non_object_json_root(
    response_body: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=response_body, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        batch = await NwsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            USER_AGENT,
            sleep=no_sleep,
        ).fetch()

    assert batch.observations == ()
    assert len(batch.failures) == 1
    failure = batch.failures[0]
    assert failure.reason == "invalid NWS observation: payload must be an object"
    assert response_body not in failure.reason
    assert failure.raw_payload == {"response_body": response_body}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response_body",
    [
        '{"type":"Feature","geometry":null}',
        '{"type":"Feature","geometry":null,"properties":[]}',
        '{"type":"Feature","geometry":null,"properties":"invalid"}',
    ],
)
async def test_nws_adapter_preserves_body_when_properties_are_not_an_object(
    response_body: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=response_body, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        batch = await NwsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            USER_AGENT,
            sleep=no_sleep,
        ).fetch()

    assert batch.observations == ()
    assert len(batch.failures) == 1
    failure = batch.failures[0]
    assert failure.reason == "invalid NWS observation: properties must be an object"
    assert response_body not in failure.reason
    assert failure.raw_payload == {"response_body": response_body}
    with pytest.raises(TypeError):
        cast(Any, failure.raw_payload)["response_body"] = "changed"
