"""The transactional unit-of-work boundary this service's use cases wrap every port call in.

The Protocol is the platform's (`holahost-db`) — the boundary and its three failure modes
are the same for every service — and is re-exported here so the application layer names it
alongside its own ports.
"""

from __future__ import annotations

from holahost_db import UnitOfWork

__all__ = ["UnitOfWork"]
