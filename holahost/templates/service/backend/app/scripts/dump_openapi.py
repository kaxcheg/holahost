"""Write this service's OpenAPI schema to `docs/openapi.json`.

The schema is the contract callers integrate against, and nothing versioned it: a route
renamed, a field made optional, a status code dropped — all of it changed silently, in a
diff that showed a Python edit and nothing about the wire. Committing the generated
document turns every such change into a reviewable diff, and CI re-runs this script to
fail when the committed copy and the code disagree (`make openapi-check`).

Run via `make openapi` after any interface change; commit the result alongside the code.
`--check` compares instead of writing and exits non-zero on a difference — that is what CI
runs (`make openapi-check`). It deliberately does not go through `git diff`: the check has
to work on a file that is not committed yet, and a check that rewrites the working tree
before inspecting it can only ever agree with itself.

Needs no database, no AWS and no network: only `create_app()` runs, and it builds routers
and middleware without touching the engine (that happens per request) or fetching JWKS
(PyJWT's client fetches lazily). The environment it needs is `Settings`' own, which comes
from `infra/envs/dev/.env.example` — the committed file that already lists every variable
the service reads, so a new setting cannot make this script stale without also making that
file wrong.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
_ENV_EXAMPLE = _BACKEND.parent / "infra" / "envs" / "dev" / ".env.example"
_OUTPUT = _BACKEND.parent / "docs" / "openapi.json"

# The one variable `.env.example` deliberately omits — it is a password, and dev's real one
# is only ever in the gitignored copy. Any value works: nothing here opens a connection.
_PLACEHOLDER_ENV = {"POSTGRES_PASSWORD": "not-a-real-password"}


def _load_env_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _ENV_EXAMPLE.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def _render() -> str:
    os.environ.update(_load_env_example())
    os.environ.update(_PLACEHOLDER_ENV)

    # Imported here, not at module scope: `create_app` reads settings on import of its own
    # dependency graph, so the environment has to be in place first.
    from interface.http.app import create_app

    # `sort_keys` and a trailing newline so the file is a stable artifact — otherwise a
    # dict-ordering change would show up as a spurious diff and fail CI on nothing.
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    rendered = _render()
    relative = _OUTPUT.relative_to(_BACKEND.parent)

    if "--check" in sys.argv[1:]:
        committed = _OUTPUT.read_text() if _OUTPUT.exists() else ""
        if committed != rendered:
            print(
                f"{relative} is out of date — run `make openapi` and commit the result.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"{relative} is current", file=sys.stderr)
        return

    _OUTPUT.write_text(rendered)
    print(f"wrote {relative}", file=sys.stderr)


if __name__ == "__main__":
    main()
