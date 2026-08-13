"""UC-R4: read a document's metadata (spec §8.5)."""

from __future__ import annotations

from dataclasses import dataclass

from application.dto.documents import DocumentView, GetDocumentCmd
from application.exceptions import NotFoundError
from application.ports.repos import DocumentsRepoFactory
from application.ports.uow import UnitOfWork
from application.use_cases._internal_errors import wrap_value_error
from domain.value_objects.document_id import DocumentId
from domain.value_objects.owner_subject import OwnerSubject


@dataclass
class GetDocumentUseCase:
    """UC-R4: read a document's metadata. No file or chunk text is ever returned."""

    documents_repo_factory: DocumentsRepoFactory
    uow: UnitOfWork

    @wrap_value_error
    def execute(self, cmd: GetDocumentCmd) -> DocumentView:
        """Read the document's current view.

        :raises ApplicationError: wraps a bare ``ValueError`` (e.g. a malformed
            ``document_id`` that should have already been rejected by interface-layer
            shape validation) — an internal defect, never client-fixable.
        :raises NotFoundError: the document does not exist, or belongs to another owner.
        :raises StorageUnavailableError: conscious pass-through.
        :raises ConcurrentUpdateError: conscious pass-through — a plain read, not
            retried (§8.6 scopes retry to replace/delete only).
        :raises IntegrityError: conscious pass-through.
        """
        documents_repo = self.documents_repo_factory(OwnerSubject(cmd.owner))
        # No lock: same staleness-accepted trade-off as search. Still runs inside a
        # transaction — every DocumentsRepo call does, uow is the sole boundary (§8.0).
        with self.uow:
            document = documents_repo.get(DocumentId.from_str(cmd.document_id))
            if document is None:
                raise NotFoundError
        return DocumentView.of(document)
