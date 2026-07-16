from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from wildfireops.config import Settings
from wildfireops.sources.http import (
    RetryPolicy,
    SourceUnavailable,
    fetch_with_retry,
)


REQUEST_URL = "https://sources.invalid/observations"


@pytest.mark.asyncio
async def test_fetch_with_retry_retries_503_until_success() -> None:
    attempts = 0
    observed_timeouts: list[dict[str, Any]] = []
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        observed_timeouts.append(request.extensions["timeout"])
        status_code = 503 if attempts < 3 else 200
        return httpx.Response(status_code, json={"ok": True}, request=request)

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await fetch_with_retry(
            client,
            client.build_request("GET", REQUEST_URL),
            RetryPolicy(base_delay_seconds=0.25, timeout_seconds=7.5),
            sleep=record_sleep,
            source_name="test_source",
        )

    assert response.status_code == 200
    assert attempts == 3
    assert delays == [0.25, 0.5]
    assert observed_timeouts == [
        {"connect": 7.5, "read": 7.5, "write": 7.5, "pool": 7.5},
        {"connect": 7.5, "read": 7.5, "write": 7.5, "pool": 7.5},
        {"connect": 7.5, "read": 7.5, "write": 7.5, "pool": 7.5},
    ]


@pytest.mark.asyncio
async def test_fetch_with_retry_does_not_retry_400_or_expose_request_data() -> None:
    attempts = 0
    delays: list[float] = []
    secret = "super-secret-map-key"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            400,
            text=f"upstream echoed {secret}",
            request=request,
        )

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        request = client.build_request(
            "GET",
            f"{REQUEST_URL}?MAP_KEY={secret}",
            headers={"Authorization": f"Bearer {secret}"},
        )
        with pytest.raises(SourceUnavailable) as caught:
            await fetch_with_retry(
                client,
                request,
                RetryPolicy(),
                sleep=record_sleep,
                source_name="nasa_firms",
            )

    assert attempts == 1
    assert delays == []
    assert str(caught.value) == "nasa_firms unavailable after 1 attempt (status 400)"
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)
    assert REQUEST_URL not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
async def test_fetch_with_retry_raises_stable_error_after_maximum() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, text="unstable body", request=request)

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceUnavailable) as caught:
            await fetch_with_retry(
                client,
                client.build_request("GET", REQUEST_URL),
                RetryPolicy(max_attempts=3, base_delay_seconds=0.1),
                sleep=record_sleep,
                source_name="nws",
            )

    assert attempts == 3
    assert delays == [0.1, 0.2]
    assert str(caught.value) == "nws unavailable after 3 attempts (status 503)"


@pytest.mark.asyncio
async def test_fetch_with_retry_retries_transport_errors() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("sensitive transport detail", request=request)
        return httpx.Response(200, request=request)

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await fetch_with_retry(
            client,
            client.build_request("GET", REQUEST_URL),
            RetryPolicy(),
            sleep=record_sleep,
            source_name="nws",
        )

    assert response.status_code == 200
    assert attempts == 2
    assert delays == [0.25]


@pytest.mark.asyncio
async def test_fetch_with_retry_does_not_retry_local_protocol_error() -> None:
    attempts = 0
    delays: list[float] = []
    secret = "sensitive-local-protocol-detail"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.LocalProtocolError(secret)

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceUnavailable) as caught:
            await fetch_with_retry(
                client,
                client.build_request("GET", REQUEST_URL),
                RetryPolicy(),
                sleep=record_sleep,
                source_name="nws",
            )

    assert attempts == 1
    assert delays == []
    assert str(caught.value) == "nws unavailable after 1 attempt"
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    ("make_policy", "message"),
    [
        (lambda: RetryPolicy(max_attempts=0), "max_attempts must be positive"),
        (
            lambda: RetryPolicy(base_delay_seconds=-0.1),
            "base_delay_seconds cannot be negative",
        ),
        (lambda: RetryPolicy(timeout_seconds=0.0), "timeout_seconds must be positive"),
    ],
)
def test_retry_policy_rejects_invalid_bounds(
    make_policy: Callable[[], RetryPolicy],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        make_policy()


def test_source_settings_use_safe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WILDFIREOPS_FIRMS_MAP_KEY", raising=False)
    monkeypatch.delenv("WILDFIREOPS_NWS_USER_AGENT", raising=False)

    settings = Settings()

    assert settings.firms_map_key is None
    assert settings.nws_user_agent.startswith("WildfireOps/")
    assert settings.nws_user_agent.strip() == settings.nws_user_agent


def test_source_settings_load_environment_without_exposing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "firms-map-key-from-environment"
    monkeypatch.setenv("WILDFIREOPS_FIRMS_MAP_KEY", secret)
    monkeypatch.setenv(
        "WILDFIREOPS_NWS_USER_AGENT",
        "WildfireOps tests@example.invalid",
    )

    settings = Settings()

    assert isinstance(settings.firms_map_key, SecretStr)
    assert settings.firms_map_key.get_secret_value() == secret
    assert settings.nws_user_agent == "WildfireOps tests@example.invalid"
    assert secret not in repr(settings)
    assert secret not in str(settings)
    assert secret not in repr(settings.firms_map_key)


def test_source_settings_reject_blank_nws_user_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WILDFIREOPS_NWS_USER_AGENT", "  ")

    with pytest.raises(ValidationError, match="NWS user agent must not be blank"):
        Settings()
