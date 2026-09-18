"""Hand-written fakes for application-layer ports, used across use-case tests."""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import Literal

from tests._support.builders import make_budget

from application.exceptions import DuplicateRequestError
from application.ports.generation import Generation
from domain.entities.budget import Budget
from domain.entities.model import Model
from domain.entities.usage_record import UsageRecord
from domain.value_objects.budget_scope import BudgetScope
from domain.value_objects.client_id import ClientId
from domain.value_objects.idempotency_key import IdempotencyKey
from domain.value_objects.idempotency_state import IdempotencyState
from domain.value_objects.message import Message
from domain.value_objects.provider_name import ProviderName
from domain.value_objects.usage import Usage


def _require_open_unit_of_work(port: str) -> None:
    """Fail loudly on a storage call made outside an open ``UnitOfWork``.

    Without it, a use case that dropped its ``with self.uow:`` would pass the whole unit suite and
    fail only against a real connection.
    """
    if not FakeUnitOfWork.any_open():
        raise AssertionError(
            f"{port} call outside an open UnitOfWork — every call must run inside `with uow:`"
        )


class FakeUnitOfWork:
    """A real context manager: records commits/rollbacks, does not swallow exceptions.

    Tracks, class-wide, how many are open — which is what the storage fakes and the provider fake
    read. Class-wide because the rules are "no storage call outside a transaction" and "no
    transaction held across a provider call", not facts about one particular object.
    """

    _open = 0

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    @classmethod
    def any_open(cls) -> bool:
        return cls._open > 0

    def __enter__(self) -> FakeUnitOfWork:
        FakeUnitOfWork._open += 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        FakeUnitOfWork._open -= 1
        if exc_type is None:
            self.commits += 1
        else:
            self.rollbacks += 1

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeClock:
    """Monotonic time that moves only when told: by a sleep, a provider call or a slow read."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeProvidersRepo:
    """The registry as fixed routes: each ``model_ref`` maps to its ordered candidates."""

    def __init__(
        self, *, routes: dict[str, list[Model]], downgrade: list[Model], aliases: list[str]
    ) -> None:
        self._routes = routes
        self._downgrade = downgrade
        self._aliases = aliases

    def resolve(self, model_ref: str) -> list[Model]:
        return list(self._routes.get(model_ref, []))

    def downgrade_targets(self) -> list[Model]:
        return list(self._downgrade)

    def aliases(self) -> list[str]:
        return list(self._aliases)


@dataclass(frozen=True)
class Outcome:
    """One scripted provider call: how long it takes, then what it answers or raises."""

    seconds: float
    result: Generation | Exception


@dataclass(frozen=True)
class GenerateCall:
    """What the use case asked the provider for."""

    model_id: str
    max_tokens: int
    timeout_s: float
    request_id: str
    system: str
    messages: list[Message]
    temperature: float | None
    stop: list[str] | None


class ScriptedGenerationProvider:
    """Answers each call to a model with the next outcome scripted for it.

    Every call moves the clock by its outcome's duration, so deadlines and timeouts are exercised
    without sleeping. It also enforces that no transaction is open during a provider call: a
    connection held for the seconds a generation takes would exhaust the pool.
    """

    def __init__(self, clock: FakeClock, script: dict[str, list[Outcome]]) -> None:
        self._clock = clock
        self._script = {model_id: list(outcomes) for model_id, outcomes in script.items()}
        self.calls: list[GenerateCall] = []

    def generate(
        self,
        model: Model,
        *,
        system: str,
        messages: list[Message],
        max_tokens: int,
        temperature: float | None,
        stop: list[str] | None,
        timeout_s: float,
        request_id: str,
    ) -> Generation:
        if FakeUnitOfWork.any_open():
            raise AssertionError("generate called inside an open UnitOfWork")
        self.calls.append(
            GenerateCall(
                model_id=model.id.value,
                max_tokens=max_tokens,
                timeout_s=timeout_s,
                request_id=request_id,
                system=system,
                messages=messages,
                temperature=temperature,
                stop=stop,
            )
        )
        queue = self._script.get(model.id.value)
        if not queue:
            raise AssertionError(f"no scripted outcome left for {model.id.value}")
        outcome = queue.pop(0)
        self._clock.advance(outcome.seconds)
        if isinstance(outcome.result, Exception):
            raise outcome.result
        return outcome.result

    def called_models(self) -> list[str]:
        return [call.model_id for call in self.calls]


class FakeBudgetRepo:
    """Budgets by ``(scope, key)``; an unlisted one is fresh, with nothing spent.

    Records every read. ``delay_seconds`` moves the clock on each read, standing in for a slow
    aggregate; ``error`` is raised on every read.
    """

    def __init__(
        self,
        clock: FakeClock,
        budgets: list[Budget],
        *,
        error: Exception | None,
        delay_seconds: float,
    ) -> None:
        self._clock = clock
        self._budgets: dict[tuple[BudgetScope, ClientId | ProviderName], Budget] = {
            (budget.scope, budget.key): budget for budget in budgets
        }
        self._error = error
        self._delay_seconds = delay_seconds
        self.reads: list[tuple[BudgetScope, str]] = []

    def client_state(
        self,
        scope: Literal[BudgetScope.CLIENT, BudgetScope.CLIENT_DOWNGRADE],
        client_id: ClientId,
    ) -> Budget:
        return self._read(scope, client_id)

    def provider_state(self, provider: ProviderName) -> Budget:
        return self._read(BudgetScope.PROVIDER, provider)

    def _read(self, scope: BudgetScope, key: ClientId | ProviderName) -> Budget:
        _require_open_unit_of_work("BudgetRepo")
        self.reads.append((scope, key.value))
        self._clock.advance(self._delay_seconds)
        if self._error is not None:
            raise self._error
        return self._budgets.get((scope, key)) or make_budget(scope, key)


class FakeUsageRepo:
    """Keeps appended records. ``errors`` are raised one per call, in order, before keeping any."""

    def __init__(self, *, errors: list[Exception]) -> None:
        self._errors = list(errors)
        self.added: list[UsageRecord] = []
        self.calls = 0

    def add(self, record: UsageRecord) -> None:
        _require_open_unit_of_work("UsageRepo")
        self.calls += 1
        if self._errors:
            raise self._errors.pop(0)
        self.added.append(record)


class FakeIdempotencyStore:
    """Records every call; with ``duplicate`` set, ``begin`` refuses with that state."""

    def __init__(self, *, duplicate: IdempotencyState | None) -> None:
        self._duplicate = duplicate
        self.begun: list[tuple[str, str]] = []
        self.completed: list[tuple[str, str, Usage]] = []
        self.released: list[tuple[str, str]] = []

    def begin(self, client_id: ClientId, key: IdempotencyKey) -> None:
        if self._duplicate is not None:
            raise DuplicateRequestError(state=self._duplicate)
        self.begun.append((client_id.value, key.value))

    def complete(self, client_id: ClientId, key: IdempotencyKey, usage: Usage) -> None:
        self.completed.append((client_id.value, key.value, usage))

    def release(self, client_id: ClientId, key: IdempotencyKey) -> None:
        self.released.append((client_id.value, key.value))
