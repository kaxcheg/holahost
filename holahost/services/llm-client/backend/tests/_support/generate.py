"""Assembles `GenerateUseCase` from fakes, so each test sets only what it is about."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from tests._support.builders import HAIKU, make_generation
from tests._support.fakes import (
    FakeBudgetRepo,
    FakeClock,
    FakeIdempotencyStore,
    FakeProvidersRepo,
    FakeUnitOfWork,
    FakeUsageRepo,
    Outcome,
    ScriptedGenerationProvider,
)

from application.ports.generation import Generation
from application.use_cases.generate import GenerateUseCase
from domain.entities.budget import Budget
from domain.entities.model import Model
from domain.value_objects.budget_policy import BudgetPolicy
from domain.value_objects.client_id import ClientId
from domain.value_objects.idempotency_state import IdempotencyState


def ok(seconds: float = 1.0, *, generation: Generation | None = None) -> Outcome:
    """A provider call that answers after `seconds`."""
    return Outcome(
        seconds=seconds, result=generation if generation is not None else make_generation()
    )


def fails(error: Exception, seconds: float = 1.0) -> Outcome:
    """A provider call that raises `error` after `seconds`."""
    return Outcome(seconds=seconds, result=error)


@dataclass
class Harness:
    """The use case and every fake behind it, for assertions."""

    clock: FakeClock
    providers: FakeProvidersRepo
    generation: ScriptedGenerationProvider
    budgets: FakeBudgetRepo
    usage: FakeUsageRepo
    idempotency: FakeIdempotencyStore
    uow: FakeUnitOfWork
    use_case: GenerateUseCase


def build_use_case(
    *,
    routes: dict[str, list[Model]] | None = None,
    downgrade: list[Model] | None = None,
    aliases: list[str] | None = None,
    script: dict[str, list[Outcome]] | None = None,
    budgets: list[Budget] | None = None,
    budget_error: Exception | None = None,
    budget_read_seconds: float = 0.0,
    usage_errors: list[Exception] | None = None,
    duplicate: IdempotencyState | None = None,
    default_policy: BudgetPolicy = BudgetPolicy.REJECT,
    overrides: Mapping[ClientId, BudgetPolicy] | None = None,
    random_value: float = 0.5,
) -> Harness:
    """A use case over fakes.

    By default `fast` resolves to haiku alone, which answers once after one second; every budget is
    fresh; the policy is `reject`; the jitter draw sits in the middle, so a pause is exactly the
    backoff base.
    """
    clock = FakeClock()
    uow = FakeUnitOfWork()
    providers = FakeProvidersRepo(
        routes=routes if routes is not None else {"fast": [HAIKU]},
        downgrade=downgrade if downgrade is not None else [],
        aliases=aliases if aliases is not None else ["fast"],
    )
    generation = ScriptedGenerationProvider(
        clock, script if script is not None else {HAIKU.id.value: [ok()]}
    )
    budget_repo = FakeBudgetRepo(
        clock,
        budgets if budgets is not None else [],
        error=budget_error,
        delay_seconds=budget_read_seconds,
    )
    usage = FakeUsageRepo(errors=usage_errors if usage_errors is not None else [])
    idempotency = FakeIdempotencyStore(duplicate=duplicate)
    use_case = GenerateUseCase(
        providers=providers,
        generation_provider=generation,
        budget_repo=budget_repo,
        usage_repo=usage,
        idempotency_store=idempotency,
        uow=uow,
        default_budget_policy=default_policy,
        budget_policy_overrides=overrides if overrides is not None else {},
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        random=lambda: random_value,
    )
    return Harness(
        clock=clock,
        providers=providers,
        generation=generation,
        budgets=budget_repo,
        usage=usage,
        idempotency=idempotency,
        uow=uow,
        use_case=use_case,
    )
