"""The ceilings a generation runs under.

Every time figure below is derived from the API Gateway's 30 s integration ceiling, and the output
ceiling from what fits into it. They describe the synchronous mode's boundary, not a promise — a
generation that does not fit is refused or cut rather than allowed to outlive the gateway.

Application constants rather than settings, although dev has no gateway at all: the service does
not branch on environment, or dev would accept load that prod refuses.
"""

from __future__ import annotations

PROVIDER_TIMEOUT_SECONDS = 20.0
"""One provider attempt at most; the remaining request budget may cut it shorter."""

RETRY_MAX_ATTEMPTS = 2
"""Attempts per model: the first and one repeat. A third does not fit into the request budget."""

RETRY_BACKOFF_BASE_SECONDS = 1.0
"""The first pause; each further one doubles. A provider's `Retry-After` takes priority."""

RETRY_BACKOFF_JITTER = 0.2
"""A pause varies by ±20 %, so callers failed by one outage do not repeat in lockstep."""

RETRY_TOTAL_BUDGET_SECONDS = 25.0
"""The whole request, failover included — 5 s short of the gateway ceiling for the network and
serialisation."""

MAX_OUTPUT_TOKENS = 1000
"""The ceiling on an answer; a larger `max_tokens` is truncated to it. More risks not fitting a
single attempt."""

MAX_INPUT_BYTES = 256 * 1024
"""The largest request body. A generation over more input would not fit the request budget
anyway; the edge refuses a larger body before reading it."""

MIN_TEMPERATURE = 0.0
MAX_TEMPERATURE = 1.0
"""The range every configured vendor accepts. Outside it a vendor rejects the request, which this
service answers `500` — so it is refused here as the caller's mistake it is."""

MAX_STOP_SEQUENCES = 4
"""The most stop sequences a request may name, none of them empty. The smallest limit among the
vendors a candidate chain can mix."""

MESSAGE_FRAMING_TOKENS = 16
"""Added per part (`system` and each message) to the input estimate, for the role and turn markers
a provider wraps around text. Generous on purpose: the estimate must stay an upper bound."""
