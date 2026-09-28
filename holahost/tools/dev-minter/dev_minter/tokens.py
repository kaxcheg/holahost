"""Service tokens, shaped the way `auth` will issue them by `client_credentials`.

The claims follow the platform specification's profile of a service token: `sub` is the `client_id`,
`aud` the target services, plus `iat`, `exp` and `jti`; `kid` and `alg` in the header. The services
validate them offline and cannot tell them from `auth`'s, so replacing this minter with `auth`
changes nothing on their side.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import jwt

from dev_minter.keys import ALGORITHM, SigningKey

ISSUER = "holahost-dev"
"""What the services' `EXPECTED_ISSUER` says on dev."""


@dataclass(frozen=True)
class Client:
    """One s2s client of `auth`'s registry, as far as the token it is issued goes."""

    client_id: str
    audiences: tuple[str, ...]
    ttl_seconds: int


GUEST_REPLY_CLI = Client(
    client_id="guest-reply-cli",
    audiences=("rag-documents", "llm-client"),
    ttl_seconds=900,
)
"""The console orchestrator's entry in `auth`'s client registry (the platform specification)."""


def mint(key: SigningKey, client: Client, *, now: datetime) -> str:
    """A signed service token for `client`, issued at `now`."""
    issued_at = int(now.timestamp())
    claims = {
        "iss": ISSUER,
        "sub": client.client_id,
        "client_id": client.client_id,
        "aud": list(client.audiences),
        "iat": issued_at,
        "exp": issued_at + client.ttl_seconds,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, key.private_key, algorithm=ALGORITHM, headers={"kid": key.kid})
