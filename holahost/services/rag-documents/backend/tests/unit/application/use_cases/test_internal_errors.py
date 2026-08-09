"""Tests for the wrap_value_error decorator."""

from __future__ import annotations

import pytest

from application.exceptions import ApplicationError
from application.ports.exceptions import ConcurrentUpdateError
from application.use_cases._internal_errors import wrap_value_error


class TestWrapInternalErrors:
    def test_returns_result_on_success(self) -> None:
        @wrap_value_error
        def fn(x: int) -> int:
            return x * 2

        assert fn(21) == 42

    def test_wraps_value_error_as_application_error(self) -> None:
        @wrap_value_error
        def fn() -> None:
            raise ValueError("boom")

        with pytest.raises(ApplicationError) as exc:
            fn()
        assert exc.value.code == "ERR_INTERNAL"
        assert "boom" in str(exc.value)
        assert isinstance(exc.value.__cause__, ValueError)

    def test_does_not_wrap_application_error_subclasses(self) -> None:
        @wrap_value_error
        def fn() -> None:
            raise ApplicationError("already typed")

        with pytest.raises(ApplicationError) as exc:
            fn()
        assert type(exc.value) is ApplicationError
        assert exc.value.__cause__ is None

    def test_does_not_wrap_port_level_exceptions(self) -> None:
        @wrap_value_error
        def fn() -> None:
            raise ConcurrentUpdateError

        with pytest.raises(ConcurrentUpdateError):
            fn()
