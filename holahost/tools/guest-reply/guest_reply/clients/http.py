"""One call to a platform service: what every call carries, and how an answer becomes a result or
one of this tool's errors.

Every call of a command carries the same `X-Request-ID`. On dev nothing else sets it — there is no
gateway — and it is what finds one command's run in both services' logs. The services' error
envelope is read here and nowhere else: above this module there are only this tool's error types.

A command makes its calls one after another, so nothing here is shared between threads.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx
from pydantic import BaseModel

from guest_reply.clients.auth import StaticToken
from guest_reply.errors import (
    DocumentNotFoundError,
    GuestReplyError,
    LimitReachedError,
    ProviderUnavailableError,
    RequestRejectedError,
    ServiceUnreachableError,
    TokenRejectedError,
    UnexpectedResponseError,
)

CONNECT_TIMEOUT = 5.0
"""Seconds. The services are local: a connection that takes longer means the stack is not up."""

RETRY_ON_429_MAX = 3
"""How many rate-limit waits one call makes before giving up."""

MAX_RETRY_AFTER = 60
"""The longest rate-limit wait worth making at a terminal, in seconds. The services count in hourly
windows, so a longer `Retry-After` can mean most of an hour: the operator is better told how long
than left watching a silent prompt."""

_RATE_LIMITED = "RateLimitExceededError"
_NOT_FOUND = "NotFoundError"
_UPSTREAM_LLM = "UpstreamLlmError"
# The statuses a service refuses a request's content with: the caller has to change the request.
_REJECTED_STATUSES = frozenset({400, 409, 413, 415, 422})


@dataclass(frozen=True)
class _Envelope:
    code: str
    message: str
    details: dict[str, object]


class ServiceCaller:
    """Calls one service: its origin and API base path, with the run's token and request id."""

    def __init__(
        self,
        http: httpx.Client,
        *,
        origin: str,
        api_base: str,
        token: StaticToken,
        request_id: str,
        on_wait: Callable[[int], None],
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http
        self._origin = origin
        self._api_base = api_base
        self._token = token
        self._request_id = request_id
        self._on_wait = on_wait
        self._sleep = sleep

    def fetch[M: BaseModel](
        self,
        model: type[M],
        method: str,
        path: str,
        *,
        read_timeout: float,
        json: object = None,
        data: Mapping[str, str] | None = None,
        files: Mapping[str, tuple[str, bytes]] | None = None,
    ) -> M:
        """Make the call and read its answer into `model`.

        :raises UnexpectedResponseError: the answer's body is not `model` — or as `_call`.
        """
        response = self._call(
            method, path, read_timeout=read_timeout, json=json, data=data, files=files
        )
        try:
            return model.model_validate(response.json())
        except ValueError:
            raise UnexpectedResponseError(
                f"{self._origin} answered {method} {path} with a body outside its contract",
                details={"status": response.status_code},
            ) from None

    def send(self, method: str, path: str, *, read_timeout: float) -> None:
        """Make a call whose success carries no body.

        :raises: as `_call`.
        """
        self._call(method, path, read_timeout=read_timeout)

    def _call(
        self,
        method: str,
        path: str,
        *,
        read_timeout: float,
        json: object = None,
        data: Mapping[str, str] | None = None,
        files: Mapping[str, tuple[str, bytes]] | None = None,
    ) -> httpx.Response:
        """One call, repeated only to wait out a short rate limit.

        No other repeat: a 5xx or a timeout is not retried here, since the services retry upstream
        themselves and a second layer would multiply the load on a failing provider.

        :raises TokenRejectedError: 401.
        :raises DocumentNotFoundError: 404 `NotFoundError`.
        :raises RequestRejectedError: 400, 409, 413, 415 or 422 with the error envelope.
        :raises LimitReachedError: 429 not worth waiting out, or still refused after
            `RETRY_ON_429_MAX` waits.
        :raises ProviderUnavailableError: 502 `UpstreamLlmError`.
        :raises ServiceUnreachableError: no connection, a timeout, or 503.
        :raises UnexpectedResponseError: any other status outside 2xx.
        """
        url = f"{self._origin}{self._api_base}{path}"
        timeout = httpx.Timeout(read_timeout, connect=CONNECT_TIMEOUT)
        waits = 0
        while True:
            response = self._send(method, url, timeout, json=json, data=data, files=files)
            if response.is_success:
                return response
            envelope = _envelope(response)
            wait = _rate_limit_wait(response, envelope)
            if wait is None or waits == RETRY_ON_429_MAX:
                raise _error_of(response, envelope, self._origin)
            waits += 1
            self._on_wait(wait)
            self._sleep(wait)

    def _send(
        self,
        method: str,
        url: str,
        timeout: httpx.Timeout,
        *,
        json: object,
        data: Mapping[str, str] | None,
        files: Mapping[str, tuple[str, bytes]] | None,
    ) -> httpx.Response:
        headers = {"Authorization": self._token.authorization(), "X-Request-ID": self._request_id}
        try:
            return self._http.request(
                method, url, headers=headers, timeout=timeout, json=json, data=data, files=files
            )
        except httpx.TimeoutException as error:
            raise ServiceUnreachableError(
                f"{self._origin} did not answer in time ({type(error).__name__})"
            ) from error
        except httpx.TransportError as error:
            raise ServiceUnreachableError(
                f"{self._origin} is unreachable ({type(error).__name__}) — is its stack up?"
            ) from error


def _rate_limit_wait(response: httpx.Response, envelope: _Envelope | None) -> int | None:
    """Seconds to wait before repeating the call, or `None` if this refusal is not worth waiting
    out within a command: a budget resets once a day, and a long window is the operator's to
    wait."""
    if response.status_code != 429:
        return None
    if envelope is None or envelope.code != _RATE_LIMITED:
        return None
    try:
        seconds = int(response.headers["Retry-After"])
    except (KeyError, ValueError):
        return None
    return seconds if 0 <= seconds <= MAX_RETRY_AFTER else None


def _error_of(response: httpx.Response, envelope: _Envelope | None, origin: str) -> GuestReplyError:
    """The error a refused call raises.

    401 and 503 come from the services' authentication middleware, ahead of their error handling,
    with a bare `{"detail": ...}` body — so they are told apart by status alone.
    """
    status = response.status_code
    if status == 401:
        return TokenRejectedError(
            f"{origin} refused the token — expired, or not minted for this stack; mint a new one: "
            "make -s -C holahost/tools/dev-minter token"
        )
    if status == 503:
        return ServiceUnreachableError(
            f"{origin} cannot validate tokens right now (503) — on dev, is the dev minter up, and "
            "does the service's JWKS_URL name it (http://dev-minter:8081/.well-known/jwks.json)?"
        )
    if envelope is None:
        return UnexpectedResponseError(
            f"{origin} answered {status} outside its contract — does the URL point at the right "
            "service?",
            details={"status": status},
        )
    code, details = envelope.code, envelope.details
    if status == 404 and code == _NOT_FOUND:
        return DocumentNotFoundError("document not found", code=code, details=details)
    if status == 429:
        return LimitReachedError(envelope.message, code=code, details=details)
    if status == 502 and code == _UPSTREAM_LLM:
        return ProviderUnavailableError(
            "the LLM provider is unavailable; llm-client already retried — try again later",
            code=code,
            details=details,
        )
    if status in _REJECTED_STATUSES:
        return RequestRejectedError(envelope.message, code=code, details=details)
    return UnexpectedResponseError(envelope.message, code=code, details=details)


def _envelope(response: httpx.Response) -> _Envelope | None:
    """The platform's error envelope `{"error": {code, message, details}}`, or `None` if the body
    is not one."""
    try:
        body = response.json()
    except ValueError:
        return None
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict) or not isinstance(error.get("code"), str):
        return None
    message = error.get("message")
    details = error.get("details")
    return _Envelope(
        code=error["code"],
        message=message if isinstance(message, str) else "",
        details=details if isinstance(details, dict) else {},
    )
