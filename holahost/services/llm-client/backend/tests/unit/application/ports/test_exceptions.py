"""Tests for the exceptions the generation provider port raises."""

from __future__ import annotations

from holahost_http import PlatformError
from tests._support.builders import make_usage

from application.ports.exceptions import (
    ProviderRefusedContentError,
    ProviderRejectedRequestError,
    TransientProviderError,
)


class TestTransientProviderError:
    def test_carries_status_and_retry_after(self) -> None:
        error = TransientProviderError("overloaded", status=529, retry_after=3.0)
        assert (error.status, error.retry_after, str(error)) == (529, 3.0, "overloaded")

    def test_a_timeout_has_no_status(self) -> None:
        assert TransientProviderError("timed out", status=None, retry_after=None).status is None


class TestProviderRejectedRequestError:
    def test_carries_status(self) -> None:
        error = ProviderRejectedRequestError("key revoked", status=401)
        assert (error.status, str(error)) == (401, "key revoked")


class TestProviderRefusedContentError:
    def test_carries_the_confirmed_usage(self) -> None:
        assert ProviderRefusedContentError(usage=make_usage(40, 2)).usage == make_usage(40, 2)


class TestNoneIsPublished:
    def test_none_is_a_platform_error(self) -> None:
        # They never reach the wire themselves: the use case retries them, fails over on them,
        # or turns them into a published error.
        errors: list[Exception] = [
            TransientProviderError("x", status=None, retry_after=None),
            ProviderRejectedRequestError("x", status=None),
            ProviderRefusedContentError(usage=make_usage()),
        ]
        for error in errors:
            assert not isinstance(error, PlatformError)
