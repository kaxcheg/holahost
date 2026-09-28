"""`rag-documents`: create, replace, search and delete a document.

The tool does not look inside the file: it sends the bytes and the file's name, and the service
parses, chunks and embeds. A document's owner is the token's subject — nothing here names one.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from guest_reply.clients.http import ServiceCaller

API_BASE = "/api/rag-documents"

SEARCH_READ_TIMEOUT = 10.0
"""Search and delete, in seconds: headroom over the service's search budget."""

INGEST_READ_TIMEOUT = 35.0
"""Create and replace, in seconds: a little over the services' synchronous ceiling, so that their
own error reaches the operator rather than a client-side cut-off."""


class CreatedDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    chunk_count: int


class Chunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    text: str
    page: int | None
    score: float


class _SearchResult(BaseModel):
    chunks: list[Chunk]


class DocumentsClient:
    """The documents service. Every method is one call; each raises what `ServiceCaller` does."""

    def __init__(self, caller: ServiceCaller) -> None:
        self._caller = caller

    def create(self, content: bytes, *, filename: str, name: str) -> CreatedDocument:
        """A new document from a file's bytes.

        :raises RequestRejectedError: the service refused the file itself — its format, its size,
            no text in it, too many chunks.
        """
        return self._caller.fetch(
            CreatedDocument,
            "POST",
            "/documents",
            read_timeout=INGEST_READ_TIMEOUT,
            data={"name": name},
            files={"file": (filename, content)},
        )

    def replace(
        self, document_id: str, content: bytes, *, filename: str, name: str | None
    ) -> CreatedDocument:
        """Replace a document's content in one call, atomically on the service's side; the id
        stays. Without `name` the service keeps the previous one.

        :raises DocumentNotFoundError: no such document, or another subject's.
        :raises RequestRejectedError: as `create`; the previous version stays in place.
        """
        return self._caller.fetch(
            CreatedDocument,
            "PUT",
            f"/documents/{document_id}",
            read_timeout=INGEST_READ_TIMEOUT,
            data={} if name is None else {"name": name},
            files={"file": (filename, content)},
        )

    def search(self, document_id: str, query: str) -> list[Chunk]:
        """The chunks relevant to `query`, best first — empty when none clears the service's
        similarity threshold.

        :raises DocumentNotFoundError: no such document, or another subject's.
        """
        result = self._caller.fetch(
            _SearchResult,
            "POST",
            f"/documents/{document_id}/search",
            read_timeout=SEARCH_READ_TIMEOUT,
            json={"query": query},
        )
        return result.chunks

    def delete(self, document_id: str) -> None:
        """Delete a document and its chunks.

        :raises DocumentNotFoundError: no such document, or another subject's.
        """
        self._caller.send("DELETE", f"/documents/{document_id}", read_timeout=SEARCH_READ_TIMEOUT)
