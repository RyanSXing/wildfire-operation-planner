import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from math import isfinite
from threading import Lock

import httpx


Sleep = Callable[[float], Awaitable[None]]

_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_RETRYABLE_TRANSPORT_ERRORS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.ProxyError,
    httpx.RemoteProtocolError,
)
_SOURCE_HTTP_LOGGER_NAMES = (
    "httpx",
    "httpcore.connection",
    "httpcore.proxy",
    "httpcore.socks",
    "httpcore.http11",
    "httpcore.http2",
)
_SUPPRESS_SOURCE_HTTP_LOGS = ContextVar(
    "wildfireops_suppress_source_http_logs",
    default=False,
)


class _SourceHttpLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _SUPPRESS_SOURCE_HTTP_LOGS.get()


_SOURCE_HTTP_LOG_FILTER = _SourceHttpLogFilter()
_SOURCE_HTTP_LOG_FILTER_LOCK = Lock()
_source_http_log_filter_installed = False


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.25
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts < 1
        ):
            raise ValueError("max_attempts must be a positive integer")
        if (
            isinstance(self.base_delay_seconds, bool)
            or not isinstance(self.base_delay_seconds, (int, float))
            or not isfinite(self.base_delay_seconds)
            or self.base_delay_seconds < 0
        ):
            raise ValueError("base_delay_seconds must be a finite non-negative number")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a finite positive number")


class SourceUnavailable(RuntimeError):
    def __init__(
        self,
        source_name: str,
        attempts: int,
        status_code: int | None = None,
    ) -> None:
        attempt_word = "attempt" if attempts == 1 else "attempts"
        message = f"{source_name} unavailable after {attempts} {attempt_word}"
        if status_code is not None:
            message = f"{message} (status {status_code})"
        super().__init__(message)
        self.source_name = source_name
        self.attempts = attempts
        self.status_code = status_code


async def fetch_with_retry(
    client: httpx.AsyncClient,
    request: httpx.Request,
    policy: RetryPolicy,
    *,
    sleep: Sleep = asyncio.sleep,
    source_name: str = "source",
) -> httpx.Response:
    for attempt in range(1, policy.max_attempts + 1):
        try:
            response = await _send_without_third_party_logs(
                client,
                _request_for_attempt(request, policy),
            )
        except _RETRYABLE_TRANSPORT_ERRORS:
            if attempt == policy.max_attempts:
                raise SourceUnavailable(source_name, attempt) from None
        except httpx.TransportError:
            raise SourceUnavailable(source_name, attempt) from None
        except httpx.RequestError:
            raise SourceUnavailable(source_name, attempt) from None
        else:
            if response.is_success:
                return response

            status_code = response.status_code
            await response.aclose()
            if (
                status_code not in _RETRYABLE_STATUS_CODES
                or attempt == policy.max_attempts
            ):
                raise SourceUnavailable(
                    source_name,
                    attempt,
                    status_code,
                ) from None

        await sleep(policy.base_delay_seconds * 2 ** (attempt - 1))

    raise AssertionError("retry loop exhausted without returning or raising")


async def _send_without_third_party_logs(
    client: httpx.AsyncClient,
    request: httpx.Request,
) -> httpx.Response:
    _install_source_http_log_filter()
    token = _SUPPRESS_SOURCE_HTTP_LOGS.set(True)
    try:
        return await client.send(request, follow_redirects=False)
    finally:
        _SUPPRESS_SOURCE_HTTP_LOGS.reset(token)


def _install_source_http_log_filter() -> None:
    global _source_http_log_filter_installed
    if _source_http_log_filter_installed:
        return
    with _SOURCE_HTTP_LOG_FILTER_LOCK:
        if _source_http_log_filter_installed:
            return
        for logger_name in _SOURCE_HTTP_LOGGER_NAMES:
            logging.getLogger(logger_name).addFilter(_SOURCE_HTTP_LOG_FILTER)
        _source_http_log_filter_installed = True


def _request_for_attempt(
    request: httpx.Request,
    policy: RetryPolicy,
) -> httpx.Request:
    extensions = dict(request.extensions)
    extensions["timeout"] = httpx.Timeout(policy.timeout_seconds).as_dict()
    return httpx.Request(
        request.method,
        request.url,
        headers=request.headers.copy(),
        content=request.content,
        extensions=extensions,
    )
