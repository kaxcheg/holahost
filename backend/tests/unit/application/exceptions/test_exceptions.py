from application.exceptions import (
    ApplicationError,
    EmptyDocumentError,
    InvalidApiKeyError,
    InvalidMagicLinkError,
    InvalidPayloadError,
    NoGuidebookAttachedError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitExceededError,
    SampleBudgetExhaustedError,
    TooManyChunksError,
    UnsupportedMediaTypeError,
    UpstreamEmailError,
    UpstreamLLMError,
)

ALL_SUBCLASSES = [
    InvalidMagicLinkError,
    InvalidApiKeyError,
    NotFoundError,
    InvalidPayloadError,
    NoGuidebookAttachedError,
    PayloadTooLargeError,
    TooManyChunksError,
    UnsupportedMediaTypeError,
    EmptyDocumentError,
    RateLimitExceededError,
    SampleBudgetExhaustedError,
    UpstreamLLMError,
    UpstreamEmailError,
]


class TestErrorCodes:
    def test_base_code_is_internal(self) -> None:
        assert ApplicationError.code == "ERR_INTERNAL"

    def test_subclass_codes(self) -> None:
        assert InvalidMagicLinkError.code == "ERR_INVALID_MAGIC_LINK"
        assert InvalidApiKeyError.code == "ERR_INVALID_API_KEY"
        assert NotFoundError.code == "ERR_NOT_FOUND"
        assert InvalidPayloadError.code == "ERR_INVALID_PAYLOAD"
        assert NoGuidebookAttachedError.code == "ERR_NO_GUIDEBOOK"
        assert PayloadTooLargeError.code == "ERR_PAYLOAD_TOO_LARGE"
        assert TooManyChunksError.code == "ERR_TOO_MANY_CHUNKS"
        assert UnsupportedMediaTypeError.code == "ERR_UNSUPPORTED_MEDIA_TYPE"
        assert EmptyDocumentError.code == "ERR_EMPTY_DOCUMENT"
        assert RateLimitExceededError.code == "ERR_RATE_LIMIT"
        assert SampleBudgetExhaustedError.code == "ERR_SAMPLE_BUDGET_EXHAUSTED"
        assert UpstreamLLMError.code == "ERR_UPSTREAM_LLM"
        assert UpstreamEmailError.code == "ERR_UPSTREAM_EMAIL"

    def test_all_are_application_errors(self) -> None:
        for exc in ALL_SUBCLASSES:
            assert issubclass(exc, ApplicationError)


class TestDetailsDict:
    def test_base_and_contextless_are_empty(self) -> None:
        assert ApplicationError().details_dict() == {}
        assert InvalidMagicLinkError().details_dict() == {}
        assert InvalidApiKeyError().details_dict() == {}
        assert NoGuidebookAttachedError().details_dict() == {}
        assert EmptyDocumentError().details_dict() == {}

    def test_not_found(self) -> None:
        assert NotFoundError(resource="guidebook").details_dict() == {"resource": "guidebook"}

    def test_invalid_payload_fields(self) -> None:
        e = InvalidPayloadError("bad name", field="name", reason="empty")
        assert e.details_dict() == {"field": "name", "reason": "empty"}
        assert "bad name" in str(e)

    def test_invalid_payload_defaults(self) -> None:
        assert InvalidPayloadError("x").details_dict() == {"field": None, "reason": None}

    def test_payload_too_large(self) -> None:
        assert PayloadTooLargeError(max_bytes=4_194_304).details_dict() == {"max_bytes": 4_194_304}

    def test_too_many_chunks(self) -> None:
        assert TooManyChunksError(max_chunks=500).details_dict() == {"max_chunks": 500}

    def test_unsupported_media_type(self) -> None:
        e = UnsupportedMediaTypeError(allowed=["application/pdf", "text/plain"])
        assert e.details_dict() == {"allowed": ["application/pdf", "text/plain"]}

    def test_rate_limit_wire_key_is_retry_after_s(self) -> None:
        e = RateLimitExceededError(scope="ip", retry_after_seconds=42)
        assert e.details_dict() == {"scope": "ip", "retry_after_s": 42}
        assert e.retry_after_seconds == 42  # internal attr name (D-1)

    def test_sample_budget_exhausted(self) -> None:
        e = SampleBudgetExhaustedError(reset_at="2026-06-11T00:00:00+00:00")
        assert e.details_dict() == {"reset_at": "2026-06-11T00:00:00+00:00"}

    def test_upstream_llm(self) -> None:
        e = UpstreamLLMError(retryable=True, upstream_status=503)
        assert e.details_dict() == {"upstream_status": 503, "retryable": True}

    def test_upstream_llm_status_optional(self) -> None:
        assert UpstreamLLMError(retryable=False).details_dict() == {
            "upstream_status": None,
            "retryable": False,
        }

    def test_upstream_email(self) -> None:
        assert UpstreamEmailError(retryable=True).details_dict() == {"retryable": True}
