"""The edge's values: which requests the rate limiter counts, and in which bucket."""

from __future__ import annotations

from interface.http.api_base import API_BASE_URL
from interface.http.edge import GENERATE_BUCKET, HEALTH_PATH, bucket_for


class TestBuckets:
    def test_generation_is_a_bucket_of_its_own(self) -> None:
        assert bucket_for("POST", f"{API_BASE_URL}/generate") == GENERATE_BUCKET == "generate"

    def test_health_is_not_limited(self) -> None:
        assert bucket_for("GET", HEALTH_PATH) is None
