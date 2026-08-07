import pytest

from domain.value_objects.page_number import PageNumber


class TestPageNumber:
    def test_accepts_none_for_pageless_formats(self) -> None:
        assert PageNumber(None).value is None

    def test_accepts_a_positive_page(self) -> None:
        assert PageNumber(1).value == 1

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            PageNumber(0)

    def test_rejects_a_negative_page(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            PageNumber(-1)
