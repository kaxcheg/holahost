"""Read a document's metadata."""

from __future__ import annotations

from dataclasses import dataclass

from application.dto.documents import DocumentView, GetDocumentCmd
from application.exceptions import NotFoundError
from application.ports.repos import DocumentsRepoFactory
from application.ports.uow import UnitOfWork
from domain.value_objects.document_id import DocumentId
from domain.value_objects.owner_subject import OwnerSubject


@dataclass
class GetDocumentUseCase:
    """Read a document's metadata. No file or chunk text is ever returned."""

    documents_repo_factory: DocumentsRepoFactory
    uow: UnitOfWork

    def execute(self, cmd: GetDocumentCmd) -> DocumentView:
        """Read the document's current view.

        :raises DomainValidationError: with `field` unset — a VO invariant no caller
            input could have violated (e.g. a malformed ``document_id`` that
            interface-layer shape validation should already have rejected). Passed
            through deliberately: nothing here can turn an internal defect into a
            client-fixable answer, and the interface layer answers `500` with the
            reason in the log alone (`interface/http/errors.py`).
        :raises NotFoundError: the document does not exist, or belongs to another owner.
        :raises StorageUnavailableError: conscious pass-through.
        :raises ConcurrentUpdateError: conscious pass-through — a plain read, not
            retried — only replace and delete retry on conflict.
        :raises IntegrityError: conscious pass-through.
        """
        documents_repo = self.documents_repo_factory(OwnerSubject(cmd.owner))
        # No lock: same staleness-accepted trade-off as search. Still runs inside a
        # transaction — every DocumentsRepo call does, uow is the sole boundary.
        with self.uow:
            document = documents_repo.get(DocumentId.from_str(cmd.document_id))
            if document is None:
                raise NotFoundError
        return DocumentView.of(document)
