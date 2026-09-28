"""Generate an answer — the service's one use case."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from holahost_db import retry_on_concurrent_update

from application.dto.generation import GenerateCmd, GenerateResult, MessageInput
from application.estimates import (
    effective_max_tokens,
    estimate_input_tokens,
    generation_seconds,
    max_tokens_within,
)
from application.exceptions import (
    BudgetExhaustedError,
    ContentRefusedError,
    ContextOverflowError,
    InvalidPayloadError,
    RequestTooSlowForSyncError,
    UnknownModelError,
    UpstreamLlmError,
    UsageNotRecordedError,
)
from application.limits import (
    MAX_OUTPUT_TOKENS,
    MAX_STOP_SEQUENCES,
    MAX_TEMPERATURE,
    MIN_TEMPERATURE,
    PROVIDER_TIMEOUT_SECONDS,
    RETRY_BACKOFF_BASE_SECONDS,
    RETRY_BACKOFF_JITTER,
    RETRY_MAX_ATTEMPTS,
    RETRY_TOTAL_BUDGET_SECONDS,
)
from application.ports.budgets import BudgetRepo
from application.ports.exceptions import (
    ConcurrentUpdateError,
    IntegrityError,
    ProviderRefusedContentError,
    ProviderRejectedRequestError,
    StorageUnavailableError,
    TransientProviderError,
)
from application.ports.generation import GenerationProvider
from application.ports.idempotency import IdempotencyStore
from application.ports.providers import ProvidersRepo
from application.ports.uow import UnitOfWork
from application.ports.usage import UsageRepo
from domain.entities.budget import Budget
from domain.entities.model import Model
from domain.entities.usage_record import UsageRecord
from domain.exceptions import DomainValidationError
from domain.value_objects.budget_policy import BudgetPolicy
from domain.value_objects.budget_scope import BudgetScope
from domain.value_objects.client_id import ClientId
from domain.value_objects.idempotency_key import MAX_IDEMPOTENCY_KEY_LENGTH, IdempotencyKey
from domain.value_objects.message import Message
from domain.value_objects.provider_name import ProviderName
from domain.value_objects.role import Role
from domain.value_objects.subject import Subject
from domain.value_objects.usage import Usage


@dataclass
class _Call:
    """What one execution carries, and what it accumulates across attempts and candidates."""

    cmd: GenerateCmd
    client_id: ClientId
    subject: Subject
    messages: list[Message]
    key: IdempotencyKey | None
    requested_model: Model
    deadline: float
    input_tokens: int
    downgraded: bool
    key_settled: bool
    attempts: int
    provider_seconds: float
    transient_failures: int
    provider_timeouts: int
    last_transient_status: int | None
    rejection: ProviderRejectedRequestError | None
    provider_budgets: dict[ProviderName, Budget]


@dataclass
class GenerateUseCase:
    """Resolve the model, check what can be checked locally, then pay a provider for an answer.

    The order is cheapest first: whatever can be refused without reaching outside is refused before
    a budget is read, and a budget before a provider is paid. Writing the usage record is the last
    step, and only a call the provider confirmed usage for reaches it.

    Time is injected — `monotonic`, `sleep`, `random` — because the retry policy is timing: tests
    drive a fake clock instead of waiting out real backoff.

    Constructed per request — together with the unit of work and the two repositories that read
    through it, which hold that exact instance. It is one connection slot, so a single set shared by
    the thread pool would have two requests committing and closing each other's transactions. The
    registry, the generation provider and the idempotency store are process-wide.
    """

    providers: ProvidersRepo
    generation_provider: GenerationProvider
    budget_repo: BudgetRepo
    usage_repo: UsageRepo
    idempotency_store: IdempotencyStore
    uow: UnitOfWork
    default_budget_policy: BudgetPolicy
    budget_policy_overrides: Mapping[ClientId, BudgetPolicy]
    monotonic: Callable[[], float]
    sleep: Callable[[float], None]
    random: Callable[[], float]

    def execute(self, cmd: GenerateCmd) -> GenerateResult:
        """Generate an answer for `cmd`.

        :raises DomainValidationError: with `field` unset — `client_id` or `subject` is empty, or an
            invariant no caller input could violate is broken. Passed through deliberately: the
            interface answers `500` with the reason in the log alone.
        :raises InvalidPayloadError: `messages` is empty, holds an unknown role or a blank message,
            the idempotency key is outside 1..128 characters, `max_tokens` is below 1,
            `temperature` is outside 0..1, or `stop` names more than four sequences or an empty one.
        :raises UnknownModelError: `model_ref` resolves to no model of an enabled provider.
        :raises DuplicateRequestError: conscious pass-through from `IdempotencyStore.begin`.
        :raises ContextOverflowError: the input estimate plus `max_tokens` exceeds the context of
            the model to call.
        :raises RequestTooSlowForSyncError: a full answer cannot finish in the time left — before
            any call, or because the time ran out before the first attempt could start.
        :raises BudgetExhaustedError: a ceiling the request would be charged to is exhausted.
        :raises UpstreamLlmError: no candidate answered and at least one failed transiently.
        :raises ContentRefusedError: the model declined the content; the spend is recorded.
        :raises ProviderRejectedRequestError: every candidate's vendor rejected the request — a
            defect of this service's configuration or adapter, passed through to be answered `500`.
        :raises UsageNotRecordedError: a paid call's record could not be written — carries the
            confirmed spend for the completion event; answered `500`.
        :raises StorageUnavailableError: conscious pass-through from a budget read.
        :raises ConcurrentUpdateError: conscious pass-through from a budget read — repeating a
            cancelled aggregate would spend the time budget.
        :raises IntegrityError: conscious pass-through from a budget read — the app role lacks a
            grant, a deploy defect.
        """
        deadline = self.monotonic() + RETRY_TOTAL_BUDGET_SECONDS
        client_id = ClientId(cmd.client_id)
        subject = Subject(cmd.subject)
        messages = _messages(cmd.messages)
        key = _idempotency_key(cmd.idempotency_key)
        _check_max_tokens(cmd.max_tokens)
        _check_temperature(cmd.temperature)
        _check_stop(cmd.stop)

        candidates = self.providers.resolve(cmd.model_ref)
        if not candidates:
            raise UnknownModelError(
                requested=cmd.model_ref, available_aliases=self.providers.aliases()
            )

        call = _Call(
            cmd=cmd,
            client_id=client_id,
            subject=subject,
            messages=messages,
            key=key,
            requested_model=candidates[0],
            deadline=deadline,
            input_tokens=estimate_input_tokens(cmd.system, messages),
            downgraded=False,
            key_settled=False,
            attempts=0,
            provider_seconds=0.0,
            transient_failures=0,
            provider_timeouts=0,
            last_transient_status=None,
            rejection=None,
            provider_budgets={},
        )
        if key is None:
            return self._generate(call, candidates)

        self.idempotency_store.begin(client_id, key)
        try:
            return self._generate(call, candidates)
        except Exception:
            # Released only while nothing has been paid for — otherwise the key stays in flight
            # until its TTL and blocks an honest repeat. Once a provider has charged, the key was
            # completed where the spend was recorded, and releasing it would let the repeat buy
            # the same answer twice.
            if not call.key_settled:
                self.idempotency_store.release(client_id, key)
            raise

    def _generate(self, call: _Call, candidates: list[Model]) -> GenerateResult:
        self._judge(call, candidates[0])
        return self._call_candidates(call, self._apply_budget(call, candidates))

    def _judge(self, call: _Call, model: Model) -> None:
        """Refuse a request `model` cannot serve: too large for its context, or too slow."""
        max_tokens = effective_max_tokens(call.cmd.max_tokens, model)
        estimated = call.input_tokens + max_tokens
        if estimated > model.max_context:
            raise ContextOverflowError(max_context=model.max_context, estimated=estimated)
        remaining = self._remaining(call)
        if generation_seconds(max_tokens, model) > min(remaining, PROVIDER_TIMEOUT_SECONDS):
            raise _too_slow(model, remaining)

    def _apply_budget(self, call: _Call, candidates: list[Model]) -> list[Model]:
        """Refuse on an exhausted budget, or move the request to the downgrade targets.

        One short transaction for every read: none of it may stay open across a provider call.

        A candidate's provider is read only when the ones before it are out of budget, so an
        ordinary call stays at two aggregates.

        :return: The candidates to call — the requested ones, or the downgrade targets.
        """
        with self.uow:
            first = self._provider_budget(call, candidates[0].provider.name)
            if first.is_exhausted and not any(
                self._fits(call, model)
                and not self._provider_budget(call, model.provider.name).is_exhausted
                for model in candidates[1:]
            ):
                # A provider out of budget is passed over, as one that failed is: what cannot
                # answer is a provider, not the request. Refused only when no candidate is left —
                # and then whatever the client's policy.
                raise _exhausted(first)
            client_budget = self.budget_repo.client_state(BudgetScope.CLIENT, call.client_id)
            if not client_budget.is_exhausted:
                return candidates

            policy = self.budget_policy_overrides.get(call.client_id, self.default_budget_policy)
            if policy is BudgetPolicy.REJECT:
                raise _exhausted(client_budget)
            pool = self.budget_repo.client_state(BudgetScope.CLIENT_DOWNGRADE, call.client_id)
            if pool.is_exhausted:
                raise _exhausted(pool)
            targets = [
                target
                for target in self.providers.downgrade_targets()
                # A model the request could already be answered by is no downgrade: it would
                # only hand the caller a second budget for the same model.
                if target not in candidates
                and self._fits(call, target)
                and not self._provider_budget(call, target.provider.name).is_exhausted
            ]
            if not targets:
                # A target that cannot serve the request is passed over, as a failover candidate
                # is. What the caller then ran out of is its own budget: it never asked for the
                # cheaper model, and that model's context or provider is not its to fix.
                raise _exhausted(client_budget)
        call.downgraded = True
        return targets

    def _provider_budget(self, call: _Call, provider: ProviderName) -> Budget:
        """A provider's budget, read at most once per call. Call inside an open unit of work."""
        if provider not in call.provider_budgets:
            call.provider_budgets[provider] = self.budget_repo.provider_state(provider)
        return call.provider_budgets[provider]

    def _call_candidates(self, call: _Call, candidates: list[Model]) -> GenerateResult:
        for index, model in enumerate(candidates):
            if not self._usable(call, model):
                continue
            result = self._attempt(call, model, failed_over=index > 0)
            if result is not None:
                return result

        if call.transient_failures > 0:
            raise UpstreamLlmError(
                attempts=call.attempts,
                upstream_status=call.last_transient_status,
                provider_timeouts=call.provider_timeouts,
            )
        if call.rejection is not None:
            raise call.rejection
        # No provider was called at all: the time ran out first, and blaming the upstream would be
        # false. Measured against the model the caller asked for — after a downgrade the candidates
        # are targets it never named, and a `max_tokens` derived from one of those answers a
        # question it did not ask.
        raise _too_slow(call.requested_model, self._remaining(call))

    def _fits(self, call: _Call, model: Model) -> bool:
        """Whether the request fits `model`: its context window, and one attempt's worth of time."""
        max_tokens = effective_max_tokens(call.cmd.max_tokens, model)
        if call.input_tokens + max_tokens > model.max_context:
            return False
        attempt_budget = min(self._remaining(call), PROVIDER_TIMEOUT_SECONDS)
        return generation_seconds(max_tokens, model) <= attempt_budget

    def _usable(self, call: _Call, model: Model) -> bool:
        """Whether a candidate can take the request.

        A candidate that cannot is skipped rather than refused: the request is not what failed, a
        provider is, and a context or budget refusal would send the caller after the wrong cause.
        A provider's budget not read with the budget check is read only now, so a call that never
        fails over stays at the budget reads of the main path.
        """
        if not self._fits(call, model):
            return False
        if model.provider.name not in call.provider_budgets:
            with self.uow:
                self._provider_budget(call, model.provider.name)
        return not call.provider_budgets[model.provider.name].is_exhausted

    def _attempt(self, call: _Call, model: Model, *, failed_over: bool) -> GenerateResult | None:
        """Call `model`, repeating transient failures while a full answer still fits the deadline.

        :return: The result, or `None` when the next candidate should be tried.
        :raises ContentRefusedError: the model declined the content.
        """
        max_tokens = effective_max_tokens(call.cmd.max_tokens, model)
        needed = generation_seconds(max_tokens, model)
        for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
            attempt_budget = min(self._remaining(call), PROVIDER_TIMEOUT_SECONDS)
            if needed > attempt_budget:
                # Started anyway, a paid generation would be cut off by our own timeout — and a
                # timed-out call's spend never reaches the usage log.
                return None
            call.attempts += 1
            started = self.monotonic()
            try:
                generation = self.generation_provider.generate(
                    model,
                    system=call.cmd.system,
                    messages=call.messages,
                    max_tokens=max_tokens,
                    temperature=call.cmd.temperature,
                    stop=call.cmd.stop,
                    timeout_s=attempt_budget,
                    request_id=call.cmd.request_id,
                )
            except TransientProviderError as error:
                call.provider_seconds += self.monotonic() - started
                call.transient_failures += 1
                call.last_transient_status = error.status
                if error.status is None:
                    call.provider_timeouts += 1
                if attempt == RETRY_MAX_ATTEMPTS:
                    return None
                # Clamped: a vendor's `Retry-After` may arrive as a date already past, and a
                # negative pause would fail the sleep itself rather than the request.
                pause = max(
                    0.0,
                    error.retry_after if error.retry_after is not None else self._backoff(attempt),
                )
                if pause + needed > self._remaining(call):
                    return None  # another vendor needs no wait
                self.sleep(pause)
            except ProviderRejectedRequestError as error:
                call.provider_seconds += self.monotonic() - started
                call.rejection = error
                return None
            except ProviderRefusedContentError as error:
                elapsed = self.monotonic() - started
                call.provider_seconds += elapsed
                self._record(call, model, error.usage, elapsed, failed_over=failed_over)
                raise ContentRefusedError(
                    provider=model.provider.name.value,
                    model=model.id.value,
                    input_tokens=error.usage.input_tokens.value,
                    output_tokens=error.usage.output_tokens.value,
                ) from error
            else:
                elapsed = self.monotonic() - started
                call.provider_seconds += elapsed
                self._record(call, model, generation.usage, elapsed, failed_over=failed_over)
                return GenerateResult(
                    text=generation.text,
                    input_tokens=generation.usage.input_tokens.value,
                    output_tokens=generation.usage.output_tokens.value,
                    provider=model.provider.name.value,
                    model=model.id.value,
                    finish_reason=generation.finish_reason.value,
                    downgraded=call.downgraded,
                    failed_over=failed_over,
                    attempts=call.attempts,
                    provider_timeouts=call.provider_timeouts,
                    provider_ms=round(call.provider_seconds * 1000),
                )
        return None

    def _backoff(self, attempt: int) -> float:
        """The pause after failed attempt number `attempt`: doubling from the base, ±jitter."""
        jitter = 1 + RETRY_BACKOFF_JITTER * (2 * self.random() - 1)
        return RETRY_BACKOFF_BASE_SECONDS * 2.0 ** (attempt - 1) * jitter

    def _record(
        self,
        call: _Call,
        model: Model,
        usage: Usage,
        elapsed_seconds: float,
        *,
        failed_over: bool,
    ) -> None:
        """Write the spend, then complete the key — for an answer and for a refusal alike.

        The write is retried on a conflict: the insert is idempotent by the record's identifier,
        and the generation is already paid for, so losing the record is the worst outcome.
        """
        record = UsageRecord.create(
            request_id=call.cmd.request_id,
            client_id=call.client_id,
            subject=call.subject,
            provider=model.provider.name,
            model=model.id,
            usage=usage,
            latency_ms=round(elapsed_seconds * 1000),
            downgraded=call.downgraded,
            failed_over=failed_over,
        )

        def write() -> None:
            with self.uow:
                self.usage_repo.add(record)

        try:
            retry_on_concurrent_update(write)
        except (StorageUnavailableError, ConcurrentUpdateError, IntegrityError) as error:
            raise UsageNotRecordedError(
                input_tokens=usage.input_tokens.value,
                output_tokens=usage.output_tokens.value,
                provider=model.provider.name.value,
                model=model.id.value,
                cause=error,
            ) from error
        finally:
            # Completed even when the write failed: the provider has charged for this answer, and
            # a key released here would let the repeat pay for it a second time.
            if call.key is not None:
                call.key_settled = True
                self.idempotency_store.complete(call.client_id, call.key, usage)

    def _remaining(self, call: _Call) -> float:
        return call.deadline - self.monotonic()


def _messages(inputs: list[MessageInput]) -> list[Message]:
    """The command's messages as domain values; anything the caller could fix is invalid payload."""
    if not inputs:
        raise InvalidPayloadError(field="messages")
    messages: list[Message] = []
    for item in inputs:
        try:
            role = Role(item.role)
        except ValueError as error:
            # An unknown role raises a bare `ValueError`, not the domain's type: untranslated it
            # would reach the bare-`Exception` handler and its traceback outside the JSON log.
            raise InvalidPayloadError(field="messages") from error
        try:
            messages.append(Message(role=role, text=item.text))
        except DomainValidationError as error:
            raise InvalidPayloadError(field=error.field or "messages") from error
    return messages


def _check_max_tokens(value: int | None) -> None:
    """Refuse a `max_tokens` no answer could have.

    Zero or less is not truncated to the ceiling the way a too-large value is: passed on, it buys a
    vendor's rejection — answered `500` — for a mistake the caller can fix.
    """
    if value is not None and value < 1:
        raise InvalidPayloadError(field="max_tokens", limit=MAX_OUTPUT_TOKENS)


def _check_temperature(value: float | None) -> None:
    if value is not None and not MIN_TEMPERATURE <= value <= MAX_TEMPERATURE:
        raise InvalidPayloadError(field="temperature")


def _check_stop(value: list[str] | None) -> None:
    # Empty is refused, whitespace is not: a blank line is the most common stop sequence there is.
    if value is not None and (len(value) > MAX_STOP_SEQUENCES or "" in value):
        raise InvalidPayloadError(field="stop", limit=MAX_STOP_SEQUENCES)


def _idempotency_key(value: str | None) -> IdempotencyKey | None:
    if value is None:
        return None
    try:
        return IdempotencyKey(value)
    except DomainValidationError as error:
        raise InvalidPayloadError(
            field=error.field or "idempotency_key", limit=MAX_IDEMPOTENCY_KEY_LENGTH
        ) from error


def _exhausted(budget: Budget) -> BudgetExhaustedError:
    return BudgetExhaustedError(scope=budget.scope, resets_at=budget.resets_at)


def _too_slow(model: Model, remaining: float) -> RequestTooSlowForSyncError:
    """The refusal for an answer no single attempt could finish.

    Bounded by the attempt timeout as well as by the time left: an answer longer than one attempt
    cannot be produced however much of the request budget remains, so `max_tokens_allowed` has to
    be a value a call can actually deliver rather than one that merely fits the budget.
    """
    seconds = max(min(remaining, PROVIDER_TIMEOUT_SECONDS), 0.0)
    return RequestTooSlowForSyncError(
        max_tokens_allowed=max_tokens_within(seconds, model), budget_seconds=seconds
    )
