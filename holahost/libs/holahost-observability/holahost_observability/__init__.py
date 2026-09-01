"""holahost-observability: structured JSON logging for Holahost services."""

from holahost_observability.logging import (
    CORE_LOG_FIELDS,
    OP_COMPLETED,
    STARTUP_COMPLETED,
    DisallowedLogFieldError,
    configure_logging,
    get_logger,
    log_event,
)

__all__ = [
    "CORE_LOG_FIELDS",
    "OP_COMPLETED",
    "STARTUP_COMPLETED",
    "DisallowedLogFieldError",
    "configure_logging",
    "get_logger",
    "log_event",
]
