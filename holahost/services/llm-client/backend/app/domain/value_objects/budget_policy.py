"""What happens when a client's budget runs out."""

from __future__ import annotations

from enum import StrEnum


class BudgetPolicy(StrEnum):
    """What happens when a client's own budget is exhausted.

    - `reject` — the request is refused;
    - `downgrade` — the request moves to the cheaper model and is charged to the client's
      `client_downgrade` pool.

    A client's attribute, not a budget's: a provider's budget is shared by clients whose policies
    differ, and its exhaustion is refused whatever the policy.
    """

    REJECT = "reject"
    DOWNGRADE = "downgrade"
