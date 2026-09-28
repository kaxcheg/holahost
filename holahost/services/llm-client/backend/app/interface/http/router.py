"""The generation route."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Security
from holahost_auth import TokenContext, current_token
from holahost_http import add_log_fields, bearer_scheme, log_completion

from application.dto.generation import GenerateCmd, GenerateResult
from application.use_cases.generate import GenerateUseCase
from interface.http.dependencies import get_generate_use_case
from interface.http.error_schemas import GENERATE_RESPONSES
from interface.http.schemas import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    GenerateRequest,
    GenerateResponse,
)

_bearer = bearer_scheme(
    "Platform-issued service JWT with `llm-client` in its audience. Budgets, limits and the "
    "exhaustion policy attach to its `client_id`."
)

# Prefix-free: the service's base path is applied once, for every router, by `app.py`. The bearer
# dependency is a declaration, not behaviour — the schema generator reads only the route
# signature, so a middleware-enforced requirement has to be stated here or it is absent from
# `docs/openapi.json`.
#
# `X-Request-ID` is required just as strictly and deliberately *not* declared: it is not the
# caller's to send (both entry paths attach it), and publishing it would undo
# `MalformedRequestError`'s muteness by naming the header a caller on the wrong path needs.
router = APIRouter(tags=["generation"], dependencies=[Security(_bearer)])


@router.post("/generate", response_model=GenerateResponse, responses=GENERATE_RESPONSES)
def generate(
    request: Request,
    body: GenerateRequest,
    token: Annotated[TokenContext, Depends(current_token)],
    use_case: Annotated[GenerateUseCase, Depends(get_generate_use_case)],
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION)
    ] = None,
) -> GenerateResponse:
    # Before the use case runs, so a refusal's event names what was asked for as well.
    add_log_fields(request, requested_model=body.model)
    result = use_case.execute(
        GenerateCmd(
            client_id=token.client_id,
            subject=token.subject,
            request_id=request.state.request_id,
            model_ref=body.model,
            system=body.system,
            messages=[message.to_input() for message in body.messages],
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            stop=body.stop,
            idempotency_key=idempotency_key,
        )
    )
    # Assembled by the library, as the refusal lines are, so one filter on `route` counts every
    # outcome of the route; `requested_model` comes from the fields attached above.
    log_completion(request, outcome="success", fields=_success_fields(result))
    return GenerateResponse.from_result(result)


def _success_fields(result: GenerateResult) -> dict[str, object]:
    return {
        "provider": result.provider,
        "model": result.model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "provider_ms": result.provider_ms,
        "attempts": result.attempts,
        "provider_timeouts": result.provider_timeouts,
        "downgraded": result.downgraded,
        "failed_over": result.failed_over,
    }
