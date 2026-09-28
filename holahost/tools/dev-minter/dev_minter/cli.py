"""`python -m dev_minter serve | mint` — the two things the dev stack asks of the minter.

`serve` is the container's command: it creates the key on first start and serves its JWKS on
`backbone`. `mint` prints one token to stdout and nothing else, so that
`export HOLAHOST_TOKEN=$(make -s token)` captures exactly the token.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from dev_minter.keys import load, load_or_create
from dev_minter.server import JWKS_PATH, PORT, jwks_document, make_server
from dev_minter.tokens import GUEST_REPLY_CLI, Client, mint

KEY_DIR = Path("/var/lib/dev-minter")
"""Where the container keeps the key: the compose project's volume."""


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "serve":
        key = load_or_create(args.key_dir)
        server = make_server(jwks_document(key), host=args.host, port=args.port)
        print(
            f"serving {JWKS_PATH} on {args.host}:{args.port}, kid {key.kid}",
            file=sys.stderr,
            flush=True,
        )
        server.serve_forever()
        return 0
    try:
        key = load(args.key_dir)
    except FileNotFoundError:
        print(
            f"no signing key in {args.key_dir}: the minter creates it when it starts (make dev-up)",
            file=sys.stderr,
        )
        return 1
    client = Client(
        client_id=args.client_id,
        audiences=tuple(args.audiences or GUEST_REPLY_CLI.audiences),
        ttl_seconds=args.ttl,
    )
    print(mint(key, client, now=datetime.now(UTC)))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dev-minter", description="Dev tokens and their JWKS, until auth exists."
    )
    parser.add_argument(
        "--key-dir",
        type=Path,
        default=KEY_DIR,
        help="where the signing key lives (default: %(default)s)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="serve the JWKS until stopped")
    # Every interface: inside the container the services reach it over `backbone`; the compose
    # file publishes no port to the host.
    serve.add_argument("--host", default="0.0.0.0")  # noqa: S104
    serve.add_argument("--port", type=int, default=PORT)
    token = commands.add_parser(
        "mint", help="print a token; the defaults are guest-reply-cli's registry entry"
    )
    token.add_argument("--client-id", default=GUEST_REPLY_CLI.client_id)
    token.add_argument(
        "--aud", dest="audiences", action="append", help="a target service; repeat for several"
    )
    token.add_argument(
        "--ttl",
        type=_positive,
        default=GUEST_REPLY_CLI.ttl_seconds,
        help="lifetime in seconds (default: %(default)s)",
    )
    return parser


def _positive(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number of seconds") from None
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive number of seconds")
    return number
