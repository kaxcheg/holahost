"""Typed settings, read from the environment before any network call."""

from __future__ import annotations

import httpx
from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_core import ErrorDetails
from pydantic_settings import BaseSettings, SettingsConfigDict

from guest_reply.errors import ConfigurationError

ENV_PREFIX = "HOLAHOST_"

# Plain HTTP only where the traffic stays on the machine: the tool runs against the local dev
# stack, and a bearer token sent in clear anywhere else is a leaked token.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class Settings(BaseSettings):
    """What the tool reads from the environment: each field is `HOLAHOST_<FIELD>`.

    The URLs are origins (`http://localhost:8080`), not API roots — the `/api/<svc>` path belongs
    to the service's contract and its client adds it. Two of them, because dev has no gateway: each
    service answers on its own published port.
    """

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, frozen=True, extra="ignore")

    rag_documents_url: str
    llm_client_url: str
    # The dev minter's token until `auth` exists; `client_credentials` replaces it then.
    token: SecretStr = Field(min_length=1)
    # `default` is in every stack's alias registry; a mistyped alias comes back from `llm-client`
    # as `UnknownModelError`, listing the ones it has.
    model_alias: str = Field(default="default", min_length=1)

    @field_validator("rag_documents_url", "llm_client_url")
    @classmethod
    def _an_origin(cls, value: str) -> str:
        try:
            url = httpx.URL(value)
        except httpx.InvalidURL as error:
            raise ValueError(str(error)) from error
        if url.scheme not in {"http", "https"} or not url.host:
            raise ValueError("expected an origin such as http://localhost:8080")
        if url.path not in {"", "/"} or url.query:
            raise ValueError("expected an origin without a path — the client adds /api/<service>")
        if url.scheme == "http" and url.host not in _LOCAL_HOSTS:
            raise ValueError("a non-local address requires https")
        return value.rstrip("/")


def load_settings() -> Settings:
    """Read the settings from the environment.

    :raises ConfigurationError: a variable is unset or invalid. The message names the variables and
        what is wrong with them, never a value — one of them is the token.
    """
    try:
        return Settings()
    except ValidationError as error:
        problems = {_variable(item): _problem(item) for item in error.errors()}
        listed = "; ".join(f"{name}: {problem}" for name, problem in problems.items())
        raise ConfigurationError(f"invalid configuration — {listed}", details=problems) from None


def _variable(item: ErrorDetails) -> str:
    return f"{ENV_PREFIX}{str(item['loc'][0]).upper()}"


def _problem(item: ErrorDetails) -> str:
    return "not set" if item["type"] == "missing" else item["msg"]
