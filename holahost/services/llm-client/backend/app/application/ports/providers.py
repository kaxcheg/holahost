"""Port for the registry of providers, models and aliases."""

from __future__ import annotations

from typing import Protocol

from domain.entities.model import Model


class ProvidersRepo(Protocol):
    """Resolves what a caller asks for into the models that may answer it.

    Loaded and validated when the process starts and never changed afterwards — a change is a
    rollout — so every method may be called from any thread of the pool without locking, and none
    of them fails: whatever could be wrong with the registry stopped the process from starting.
    """

    def resolve(self, model_ref: str) -> list[Model]:
        """The models that may answer a request for `model_ref`, in the order to try them.

        An alias expands to its chain; a model identifier to that model alone — a caller that named
        a model is never answered by another vendor's. Models of disabled providers are left out, so
        the first element is the one to call and the rest are failover candidates.

        :param model_ref: An alias or a model identifier, as the caller sent it.
        :return: The candidates; empty when nothing resolves.
        """
        ...

    def downgrade_targets(self) -> list[Model]:
        """The cheaper models the `downgrade` policy moves a request to, in the order to try them.

        Configured apart from the aliases, so re-pointing an alias never changes what a request
        degrades to.

        :return: The candidates; empty when no target is configured or none is enabled.
        """
        ...

    def aliases(self) -> list[str]:
        """The aliases that currently resolve — what a caller told of an unknown model may use."""
        ...
