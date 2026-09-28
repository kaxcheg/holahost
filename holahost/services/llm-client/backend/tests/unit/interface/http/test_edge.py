"""The edge's values: which requests the rate limiter counts and in which bucket, and how much
body the edge reads."""

from __future__ import annotations

from application.limits import MAX_INPUT_BYTES
from interface.http.api_base import API_BASE_URL
from interface.http.edge import GENERATE_BUCKET, HEALTH_PATH, MAX_REQUEST_BODY_SIZE, bucket_for


class TestBodyCap:
    def test_the_transport_cap_is_the_input_ceiling(self) -> None:
        # The whole JSON body, framing included: there is no inner check to advertise instead.
        assert MAX_REQUEST_BODY_SIZE == MAX_INPUT_BYTES == 256 * 1024


class TestBuckets:
    def test_generation_is_a_bucket_of_its_own(self) -> None:
        assert bucket_for("POST", f"{API_BASE_URL}/generate") == GENERATE_BUCKET == "generate"

    def test_health_is_not_limited(self) -> None:
        assert bucket_for("GET", HEALTH_PATH) is None
