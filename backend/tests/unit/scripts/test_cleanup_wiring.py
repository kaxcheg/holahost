from types import SimpleNamespace

from application.dto.cleanup import CleanupResult, RateCountersCleanupResult
from scripts.cleanup_wiring import run


def test_run_executes_both_and_returns_totals() -> None:
    expired_uc = SimpleNamespace(
        execute=lambda: CleanupResult(expired_magic_links=3, deleted_guidebooks=2)
    )
    counters_uc = SimpleNamespace(execute=lambda: RateCountersCleanupResult(deleted_windows=5))
    container = SimpleNamespace(cleanup_expired=expired_uc, cleanup_rate_counters=counters_uc)

    result = run(container)

    assert result == {
        "expired_magic_links": 3,
        "deleted_guidebooks": 2,
        "deleted_rate_windows": 5,
    }
