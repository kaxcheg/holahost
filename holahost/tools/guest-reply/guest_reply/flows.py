"""The sequence of calls behind each command — and nothing else.

The one decision taken here on what a service answered is the scenario's own: a search that found
nothing leaves nothing to generate from. Everything else is the order of the calls; errors are the
clients' and pass through as they are.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from guest_reply.clients.documents import CreatedDocument, DocumentsClient
from guest_reply.clients.generation import GenerationClient, Usage
from guest_reply.errors import (
    CleanupFailure,
    DocumentNotFoundError,
    FileUnreadableError,
    GuestReplyError,
)
from guest_reply.prompt.render import render


@dataclass(frozen=True)
class Services:
    documents: DocumentsClient
    generation: GenerationClient
    model_alias: str


@dataclass(frozen=True)
class Answer:
    text: str
    chunks_used: int
    usage: Usage
    provider: str
    model: str


@dataclass(frozen=True)
class OneShot:
    document_id: str
    answer: Answer | None
    cleanup_failure: CleanupFailure | None


def ingest(services: Services, path: Path, name: str | None) -> CreatedDocument:
    """UC-C1: one create call; without `name`, the document takes the file's name.

    :raises FileUnreadableError: before any call.
    """
    content = _read(path)
    return services.documents.create(content, filename=path.name, name=name or path.name)


def replace(services: Services, document_id: str, path: Path, name: str | None) -> CreatedDocument:
    """UC-C2: one replace call — never a delete and a create; atomicity is the service's.

    :raises FileUnreadableError: before any call.
    """
    content = _read(path)
    return services.documents.replace(document_id, content, filename=path.name, name=name)


def ask(services: Services, document_id: str, guest_message: str) -> Answer | None:
    """UC-C3: search, then generate from what was found.

    `None` when the search found nothing: generation is then not called, since an answer without
    context would read as grounded when it is not.
    """
    chunks = services.documents.search(document_id, guest_message)
    if not chunks:
        return None
    system, messages = render(chunks, guest_message)
    generated = services.generation.generate(
        system=system, messages=messages, model=services.model_alias
    )
    return Answer(
        text=generated.text,
        chunks_used=len(chunks),
        usage=generated.usage,
        provider=generated.provider,
        model=generated.model,
    )


def ask_from_file(services: Services, path: Path, guest_message: str) -> OneShot:
    """UC-C4: ingest, ask, and delete the document whatever `ask` did — nothing outlives the run.

    A failed ingest stops here: there is nothing to delete. A failure of `ask` is re-raised after
    the deletion, carrying the deletion's own failure if it had one — the deletion never replaces
    it. A failure of the deletion alone comes back in the result, beside the answer it did not
    prevent.
    """
    created = ingest(services, path, name=None)
    try:
        answer = ask(services, created.document_id, guest_message)
    except GuestReplyError as error:
        error.cleanup_failure = _delete(services, created.document_id)
        raise
    except BaseException as error:
        # A defect or an interrupt: the document is still deleted, and a failure to is noted.
        failure = _delete(services, created.document_id)
        if failure is not None:
            error.add_note(
                f"the temporary document {failure.document_id} was not deleted: "
                f"{failure.error.code}"
            )
        raise
    return OneShot(
        document_id=created.document_id,
        answer=answer,
        cleanup_failure=_delete(services, created.document_id),
    )


def remove(services: Services, document_id: str) -> None:
    """UC-C5: one delete call. A missing document is an error, not a success."""
    services.documents.delete(document_id)


def _read(path: Path) -> bytes:
    """The file's bytes, as they are: never parsed, never executed."""
    try:
        return path.read_bytes()
    except OSError as error:
        raise FileUnreadableError(
            f"cannot read {path}: {error.strerror or error}", details={"path": str(path)}
        ) from error


def _delete(services: Services, document_id: str) -> CleanupFailure | None:
    try:
        services.documents.delete(document_id)
    except DocumentNotFoundError:
        # Already gone: nothing is left behind, which is all the deletion is for.
        return None
    except GuestReplyError as error:
        return CleanupFailure(document_id=document_id, error=error)
    return None
