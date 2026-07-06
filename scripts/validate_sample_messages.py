"""Sample-messages fixture guard (C-10b, US-01 / spec section 13.3).

docs/sample_messages.json is the published SAMPLE_MESSAGES source (s3_frontend publishes it as
config/sample_messages.json; the sample screen prefills from it). The hosted check-json hook
guards syntax only; this guards the shape contract: a non-empty JSON array of non-empty strings
(in sync with the frontend's isMessageList guard, F-20).

Run via `make validate-sample-messages`; exits non-zero (listing violations) on failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PATH = _ROOT / "docs" / "sample_messages.json"


def main() -> int:
    data = json.loads(_PATH.read_text())
    errors: list[str] = []

    if not isinstance(data, list):
        errors.append(f"must be a JSON array, got {type(data).__name__}")
    elif not data:
        errors.append("array must not be empty")
    else:
        for i, item in enumerate(data):
            if not isinstance(item, str) or not item.strip():
                errors.append(f"element {i} is not a non-empty string: {item!r}")

    if errors:
        print(f"{_PATH.relative_to(_ROOT)} invalid:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"{_PATH.relative_to(_ROOT)} OK: {len(data)} sample message(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
