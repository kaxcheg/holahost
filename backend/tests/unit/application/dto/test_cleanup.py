from application.dto.cleanup import CleanupResult, RateCountersCleanupResult


class TestCleanupDTOs:
    def test_cleanup_result(self) -> None:
        r = CleanupResult(expired_leads=3, deleted_guidebooks=1)
        assert (r.expired_leads, r.deleted_guidebooks) == (3, 1)

    def test_rate_counters_result(self) -> None:
        assert RateCountersCleanupResult(deleted_windows=5).deleted_windows == 5
