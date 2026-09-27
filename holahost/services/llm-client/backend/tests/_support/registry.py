"""A valid registry file as data, for the tests that change one thing in it."""

from __future__ import annotations

from typing import Any


def model_entry(
    *,
    max_context: int = 200_000,
    max_output: int = 8192,
    tokens_per_second: int = 100,
    deprecated: bool = False,
) -> dict[str, Any]:
    """One model's figures, as the file states them."""
    return {
        "max_context": max_context,
        "max_output": max_output,
        "price_in": "1",
        "price_out": "5",
        "tokens_per_second": tokens_per_second,
        "deprecated": deprecated,
    }


def ref(provider: str, model: str) -> dict[str, str]:
    """A reference to a model, as aliases and downgrade targets hold it."""
    return {"provider": provider, "model": model}


def registry_data() -> dict[str, Any]:
    """Two providers — `anthropic` with haiku and sonnet, `other-vendor` with one model. `fast`
    fails over from haiku to the other vendor, `quality` is sonnet alone, the downgrade target is
    haiku. A fresh copy on every call, so a test may change it in place."""
    return {
        "providers": {
            "anthropic": {
                "enabled": True,
                "api_key_ref": "anthropic-api-key",
                "models": {
                    "claude-haiku-4-5": model_entry(),
                    "claude-sonnet-4-6": model_entry(tokens_per_second=60),
                },
            },
            "other-vendor": {
                "enabled": True,
                "api_key_ref": "other-vendor-api-key",
                "models": {"other-vendor-mini": model_entry()},
            },
        },
        "aliases": {
            "fast": [
                ref("anthropic", "claude-haiku-4-5"),
                ref("other-vendor", "other-vendor-mini"),
            ],
            "quality": [ref("anthropic", "claude-sonnet-4-6")],
        },
        "downgrade_targets": [ref("anthropic", "claude-haiku-4-5")],
        "on_budget_exhausted": {"default": "reject", "overrides": {}},
    }
