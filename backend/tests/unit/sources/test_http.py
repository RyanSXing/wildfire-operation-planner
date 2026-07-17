import asyncio
import logging
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from wildfireops.config import Settings
from wildfireops.sources import http as source_http
from wildfireops.sources.http import (
    RetryPolicy,
    SourceUnavailable,
    fetch_with_retry,
)


REQUEST_URL = "https://sources.invalid/observations"
APPLICATION_LOGGER = logging.getLogger("wildfireops.tests.sources")


async def no_sleep(_: float) -> None:
    pass


def enable_source_http_logging(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    for logger_name in (
        "httpx",
        "httpcore.connection",
        "httpcore.http11",
        "httpcore.http2",
        "httpcore.proxy",
        "httpcore.socks",
    ):
        caplog.set_level(logging.DEBUG, logger=logger_name)
    caplog.set_level(logging.DEBUG, logger=APPLICATION_LOGGER.name)


def assert_secret_not_logged(
    caplog: pytest.LogCaptureFixture,
    secret: str,
) -> None:
    assert all(secret not in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_source_success_suppresses_third_party_logs_only_in_its_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    enable_source_http_logging(caplog)
    secret = "success-secret-map-key"
    request_started = asyncio.Event()
    release_response = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        for logger_name in source_http._SOURCE_HTTP_LOGGER_NAMES:
            logging.getLogger(logger_name).debug(
                "source request body=%s",
                secret,
            )
        APPLICATION_LOGGER.info("in-send application log remains visible")
        request_started.set()
        await release_response.wait()
        return httpx.Response(200, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source_request = asyncio.create_task(
            fetch_with_retry(
                client,
                client.build_request(
                    "GET",
                    f"{REQUEST_URL}?MAP_KEY={secret}",
                ),
                RetryPolicy(),
                source_name="nasa_firms",
            )
        )
        await request_started.wait()
        logging.getLogger("httpx").info("concurrent unrelated HTTP request")
        APPLICATION_LOGGER.info("concurrent application log remains visible")
        release_response.set()
        await source_request

    assert_secret_not_logged(caplog, secret)
    messages = [record.getMessage() for record in caplog.records]
    assert "concurrent unrelated HTTP request" in messages
    assert "in-send application log remains visible" in messages
    assert "concurrent application log remains visible" in messages


@pytest.mark.asyncio
async def test_source_status_retry_suppresses_secret_bearing_http_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    enable_source_http_logging(caplog)
    secret = "retry-secret-map-key"
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        logging.getLogger("httpcore.http11").debug(
            "retry response body=%s",
            secret,
        )
        status_code = 503 if attempts == 1 else 200
        return httpx.Response(status_code, text=secret, request=request)

    async def log_retry_delay(_: float) -> None:
        logging.getLogger("httpx").info("retry delay HTTP log remains visible")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await fetch_with_retry(
            client,
            client.build_request("GET", f"{REQUEST_URL}?MAP_KEY={secret}"),
            RetryPolicy(max_attempts=2),
            sleep=log_retry_delay,
            source_name="nasa_firms",
        )

    assert attempts == 2
    assert_secret_not_logged(caplog, secret)
    assert "retry delay HTTP log remains visible" in [
        record.getMessage() for record in caplog.records
    ]


def test_source_http_log_filter_installation_is_idempotent_and_keeps_levels() -> None:
    loggers = [
        logging.getLogger(logger_name)
        for logger_name in source_http._SOURCE_HTTP_LOGGER_NAMES
    ]
    levels = [logger.level for logger in loggers]

    source_http._install_source_http_log_filter()
    source_http._install_source_http_log_filter()

    assert [logger.level for logger in loggers] == levels
    assert all(
        logger.filters.count(source_http._SOURCE_HTTP_LOG_FILTER) == 1
        for logger in loggers
    )


@pytest.mark.asyncio
async def test_source_transport_failure_suppresses_logs_and_resets_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    enable_source_http_logging(caplog)
    secret = "transport-secret-map-key"

    def handler(request: httpx.Request) -> httpx.Response:
        logging.getLogger("httpcore.connection").debug(
            "transport exception=%s",
            secret,
        )
        raise httpx.ConnectError(secret, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceUnavailable):
            await fetch_with_retry(
                client,
                client.build_request("GET", f"{REQUEST_URL}?MAP_KEY={secret}"),
                RetryPolicy(max_attempts=1),
                source_name="nasa_firms",
            )

    logging.getLogger("httpx").info("post-failure unrelated HTTP request")
    APPLICATION_LOGGER.info("post-failure application log remains visible")

    assert_secret_not_logged(caplog, secret)
    messages = [record.getMessage() for record in caplog.records]
    assert "post-failure unrelated HTTP request" in messages
    assert "post-failure application log remains visible" in messages


@pytest.mark.asyncio
async def test_fetch_with_retry_retries_503_until_success() -> None:
    attempts = 0
    attempt_requests: list[httpx.Request] = []
    attempt_responses: list[httpx.Response] = []
    observed_timeouts: list[dict[str, Any]] = []
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        attempt_requests.append(request)
        observed_timeouts.append(request.extensions["timeout"])
        status_code = 503 if attempts < 3 else 200
        response = httpx.Response(
            status_code,
            json={"ok": True},
            request=request,
        )
        attempt_responses.append(response)
        return response

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        caller_request = client.build_request(
            "POST",
            REQUEST_URL,
            headers={"X-Caller": "owned"},
            content=b"caller-owned-body",
            extensions={"caller": {"owned": True}},
        )
        caller_state = (
            caller_request.method,
            caller_request.url,
            caller_request.headers.copy(),
            caller_request.content,
            dict(caller_request.extensions),
        )
        response = await fetch_with_retry(
            client,
            caller_request,
            RetryPolicy(base_delay_seconds=0.25, timeout_seconds=7.5),
            sleep=record_sleep,
            source_name="test_source",
        )

    assert response.status_code == 200
    assert attempts == 3
    assert len({id(request) for request in attempt_requests}) == 3
    assert all(request is not caller_request for request in attempt_requests)
    assert all(response.is_closed for response in attempt_responses[:2])
    assert (
        caller_request.method,
        caller_request.url,
        caller_request.headers,
        caller_request.content,
        caller_request.extensions,
    ) == caller_state
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
@pytest.mark.parametrize("status_code", [408, 429, 500, 502, 504])
async def test_fetch_with_retry_retries_each_approved_status(
    status_code: int,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            status_code if attempts == 1 else 200,
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await fetch_with_retry(
            client,
            client.build_request("GET", REQUEST_URL),
            RetryPolicy(max_attempts=2),
            sleep=no_sleep,
            source_name="nws",
        )

    assert response.status_code == 200
    assert attempts == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_type",
    [
        httpx.ConnectError,
        httpx.ReadTimeout,
        httpx.ProxyError,
        httpx.RemoteProtocolError,
    ],
)
async def test_fetch_with_retry_retries_representative_transport_hierarchy(
    error_type: type[httpx.TransportError],
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise error_type("transient", request=request)
        return httpx.Response(200, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await fetch_with_retry(
            client,
            client.build_request("GET", REQUEST_URL),
            RetryPolicy(max_attempts=2),
            sleep=no_sleep,
            source_name="nws",
        )

    assert response.status_code == 200
    assert attempts == 2


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_type",
    [httpx.DecodingError, httpx.TooManyRedirects],
)
async def test_fetch_with_retry_sanitizes_non_transport_request_errors(
    error_type: type[httpx.RequestError],
) -> None:
    attempts = 0
    secret = "request-error-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise error_type(secret, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceUnavailable) as caught:
            await fetch_with_retry(
                client,
                client.build_request("GET", f"{REQUEST_URL}?key={secret}"),
                RetryPolicy(),
                source_name="nasa_firms",
            )

    assert attempts == 1
    assert str(caught.value) == "nasa_firms unavailable after 1 attempt"
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
async def test_fetch_with_retry_disables_client_redirect_following() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            302,
            headers={"Location": str(request.url)},
            request=request,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    ) as client:
        with pytest.raises(SourceUnavailable) as caught:
            await fetch_with_retry(
                client,
                client.build_request("GET", REQUEST_URL),
                RetryPolicy(),
                source_name="nws",
            )

    assert len(requests) == 1
    assert str(caught.value) == "nws unavailable after 1 attempt (status 302)"
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    "invalid_value",
    [True, False, 1.0, 1.5, 0, -1],
)
def test_retry_policy_requires_positive_integer_attempts(
    invalid_value: Any,
) -> None:
    with pytest.raises(
        ValueError,
        match="max_attempts must be a positive integer",
    ):
        RetryPolicy(max_attempts=invalid_value)


@pytest.mark.parametrize(
    "invalid_value",
    [True, False, float("nan"), float("inf"), float("-inf"), -0.1, "0.25"],
)
def test_retry_policy_requires_finite_non_negative_delay(
    invalid_value: Any,
) -> None:
    with pytest.raises(
        ValueError,
        match="base_delay_seconds must be a finite non-negative number",
    ):
        RetryPolicy(base_delay_seconds=invalid_value)


@pytest.mark.parametrize(
    "invalid_value",
    [
        True,
        False,
        float("nan"),
        float("inf"),
        float("-inf"),
        0,
        -0.1,
        "10",
    ],
)
def test_retry_policy_requires_finite_positive_timeout(
    invalid_value: Any,
) -> None:
    with pytest.raises(
        ValueError,
        match="timeout_seconds must be a finite positive number",
    ):
        RetryPolicy(timeout_seconds=invalid_value)


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
