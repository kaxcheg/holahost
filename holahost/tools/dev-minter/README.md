# dev-minter

The local stand-in for `auth`, dev only. It holds one RSA signing key, mints service tokens with it,
and serves the matching JWKS on the `backbone` network, so that the services validate tokens on dev
exactly as they will against `auth` — offline, by signature. Staging and prod never see it.

## Use

```bash
make dev-up                                   # build the image, start the minter on backbone
export HOLAHOST_TOKEN=$(make -s token)        # a token for guest-reply-cli
```

From the repository root: `export HOLAHOST_TOKEN=$(make -s -C holahost/tools/dev-minter token)`.

| Target | What it does |
|---|---|
| `dev-up` | builds `dev-minter:dev` and starts it (creates `backbone` if missing) |
| `token` | prints one token on stdout, and nothing else |
| `dev-down` | stops it; the key survives in the volume |
| `dev-down-v` | stops it and deletes the key — every token minted so far stops validating |
| `lint`, `format`, `typecheck`, `lint-imports`, `test` | the package's own gates |

## What the services see

The JWKS is at `http://dev-minter:8081/.well-known/jwks.json`, resolved by Docker's DNS from inside
the services' containers; no port is published to the host. A service's dev `.env` points at it:

```
JWKS_URL=http://dev-minter:8081/.well-known/jwks.json
EXPECTED_ALGORITHM=RS256
EXPECTED_ISSUER=holahost-dev
```

## The token

A service token as `auth` will issue it by `client_credentials`: `sub` and `client_id` are the
client's id, `aud` its target services, plus `iat`, `exp` and `jti`; `kid` and `alg` in the header.
The defaults are the `guest-reply-cli` entry of `auth`'s client registry (the platform
specification): audiences `rag-documents` and `llm-client`, a 900-second lifetime. Another client:

```bash
docker compose exec -T dev-minter python -m dev_minter mint \
  --client-id chat-assistant-api --aud rag-documents --ttl 3600
```

## The key

Created by the server on its first start, in the `keys` volume, and reused after; `mint` only
reads it, so a token is always signed by the key the JWKS carries. A new key comes with a new start
(`make dev-down-v && make dev-up`). Its `kid` is its RFC 7638 thumbprint, so a new key gets a new
`kid` — the services' JWKS client refetches on an unknown `kid`, and they pick the new key up
without a restart of their own.
