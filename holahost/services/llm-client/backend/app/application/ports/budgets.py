"""Port for reading the current window's budgets."""

from __future__ import annotations

from typing import Literal, Protocol

from domain.entities.budget import Budget
from domain.value_objects.budget_scope import BudgetScope
from domain.value_objects.client_id import ClientId
from domain.value_objects.provider_name import ProviderName


class BudgetRepo(Protocol):
    """Assembles a budget for the current window: the spend from the usage log, the ceilings from
    config. Nothing is stored — a new window is a new range of the log, with nothing to reset.

    Lock: deliberately not taken. A budget cannot be held for the seconds a generation takes, so two
    simultaneous calls may both see the remainder and both spend it; overspend within a single call
    is accepted. Call inside an open unit of work.

    A read that outruns the statement timeout arrives as `ConcurrentUpdateError`: the platform
    classes a cancelled statement with lock-wait timeouts, whose transaction is already gone. A read
    the database refuses for a missing grant arrives as `IntegrityError`, the platform's type for a
    privilege refusal — a deploy defect.
    """

    def client_state(
        self,
        scope: Literal[BudgetScope.CLIENT, BudgetScope.CLIENT_DOWNGRADE],
        client_id: ClientId,
    ) -> Budget:
        """A client's budget in one of its two pools.

        The pools do not overlap: `client` sums the client's calls that were not downgraded,
        `client_downgrade` the ones that were.

        :param scope: The pool.
        :param client_id: The client.
        :return: The budget for the current window.
        :raises StorageUnavailableError: the database is unreachable or timed out.
        :raises ConcurrentUpdateError: the aggregate was cancelled by the statement timeout.
        :raises IntegrityError: the app role lacks the grant to read the usage log.
        """
        ...

    def provider_state(self, provider: ProviderName) -> Budget:
        """Everything spent at `provider` in the current window, whoever the caller.

        :param provider: The provider.
        :return: The budget for the current window.
        :raises StorageUnavailableError: the database is unreachable or timed out.
        :raises ConcurrentUpdateError: the aggregate was cancelled by the statement timeout.
        :raises IntegrityError: the app role lacks the grant to read the usage log.
        """
        ...
