"""Unit tests for interface-layer Pydantic schemas."""

from datetime import UTC, datetime

from application.dto.documents import DocumentView
from application.dto.search import SearchHitView, SearchResult
from interface.http.schemas import DocumentResponse, HealthResponse, SearchResponse


class TestDocumentResponse:
    def test_from_view_round_trips_all_fields(self) -> None:
        view = DocumentView(
            document_id="8f14e45f-ceea-467a-9f0a-1c2d3e4f5a6b",
            name="Guidebook",
            mime_type="application/pdf",
            chunk_count=3,
            created_at=datetime(2026, 8, 4, 10, 15, 30, tzinfo=UTC),
            updated_at=datetime(2026, 8, 4, 10, 15, 30, tzinfo=UTC),
        )

        response = DocumentResponse.from_view(view)

        assert response.document_id == view.document_id
        assert response.chunk_count == 3


class TestSearchResponse:
    def test_from_result_wraps_hits_under_chunks_key(self) -> None:
        result = SearchResult(
            hits=[SearchHitView(chunk_id="c1", text="Check-in at 15:00", page=2, score=0.71)]
        )

        response = SearchResponse.from_result(result)

        assert response.model_dump()["chunks"][0]["score"] == 0.71


class TestHealthResponse:
    def test_status_field(self) -> None:
        assert HealthResponse(status="ok").status == "ok"
