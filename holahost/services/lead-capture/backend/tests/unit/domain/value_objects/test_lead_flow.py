import pytest

from domain.exceptions import DomainValidationError
from domain.value_objects.lead_flow import LeadFlow


class TestLeadFlow:
    def test_values_are_lowercase_member_names(self) -> None:
        assert LeadFlow.GUIDEBOOK.value == "guidebook"
        assert LeadFlow.SAMPLE.value == "sample"

    def test_is_str_enum(self) -> None:
        assert isinstance(LeadFlow.GUIDEBOOK, str)

    def test_lookup_by_value(self) -> None:
        assert LeadFlow("sample") is LeadFlow.SAMPLE

    def test_unknown_value_raises_domain_validation(self) -> None:
        with pytest.raises(DomainValidationError) as exc:
            LeadFlow("bogus")
        assert exc.value.field == "flow"
        assert exc.value.reason == "invalid_format"
