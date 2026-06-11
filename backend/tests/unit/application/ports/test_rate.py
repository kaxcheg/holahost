from application.ports.rate import RateLimitScope


class TestRateLimitScope:
    def test_values_match_db_scope(self) -> None:
        assert RateLimitScope.IP.value == "ip"
        assert RateLimitScope.MAGIC_LINK.value == "magic_link"

    def test_is_str_enum(self) -> None:
        assert isinstance(RateLimitScope.IP, str)

    def test_lookup_by_value(self) -> None:
        assert RateLimitScope("magic_link") is RateLimitScope.MAGIC_LINK
