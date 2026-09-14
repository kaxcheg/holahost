"""The dimensions a budget ceiling applies to."""

from __future__ import annotations

from enum import StrEnum


class BudgetScope(StrEnum):
    """The dimension a budget ceiling applies to.

    - `client` — a client's spend on the models it asked for;
    - `client_downgrade` — a client's spend on the cheaper model its policy fell back to, under a
      ceiling of its own. Ceilings are in tokens and a cheaper model spends as many tokens, so
      without a separate pool a downgrade would meet the same exhausted counter and never answer;
    - `provider` — everything spent at one provider, protecting the platform's account.
    """

    CLIENT = "client"
    CLIENT_DOWNGRADE = "client_downgrade"
    PROVIDER = "provider"
