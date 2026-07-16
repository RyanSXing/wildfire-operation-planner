import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx


Sleep = Callable[[float], Awaitable[None]]

_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_RETRYABLE_TRANSPORT_ERRORS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.ProxyError,
    httpx.RemoteProtocolError,
)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.25
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds cannot be negative")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


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
            response = await client.send(_request_for_attempt(request, policy))
        except _RETRYABLE_TRANSPORT_ERRORS:
            if attempt == policy.max_attempts:
                raise SourceUnavailable(source_name, attempt) from None
        except httpx.TransportError:
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
