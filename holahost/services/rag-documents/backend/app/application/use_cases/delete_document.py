"""UC-R5: delete a document (spec §8.5)."""

from __future__ import annotations

from dataclasses import dataclass

from application.dto.documents import DeleteDocumentCmd
from application.exceptions import NotFoundError
from application.ports.repos import DocumentsRepoFactory
from application.ports.uow import UnitOfWork
from application.use_cases._internal_errors import wrap_value_error
from application.use_cases._retry import retry_on_concurrent_update
from domain.value_objects.document_id import DocumentId
from domain.value_objects.owner_subject import OwnerSubject


@dataclass
class DeleteDocumentUseCase:
    """UC-R5: delete a document and its chunks (cascade) in one locked transaction."""

    documents_repo_factory: DocumentsRepoFactory
    uow: UnitOfWork

    @wrap_value_error
    def execute(self, cmd: DeleteDocumentCmd) -> None:
        """Delete the document, retrying on a concurrency conflict.

        :raises ApplicationError: wraps a bare ``ValueError`` (e.g. a malformed
            ``document_id`` that should have already been rejected by interface-layer
            shape validation) — an internal defect, never client-fixable.
        :raises NotFoundError: the document does not exist, or belongs to another
            owner — including on a second call for an already-deleted document
            (delete is idempotent by observable effect, US-R05).
        :raises StorageUnavailableError: conscious pass-through.
        :raises ConcurrentUpdateError: re-raised only after being retried twice (§8.6).
        :raises IntegrityError: conscious pass-through.
        """
        doc_id = DocumentId.from_str(cmd.document_id)
        owner_subject = OwnerSubject(cmd.owner)
        documents_repo = self.documents_repo_factory(owner_subject)

        def _delete() -> None:
            with self.uow:
                # Locked: idempotent delete must not race a concurrent
                # replace/delete on the same document.
                document = documents_repo.get(doc_id, lock=True)
                if document is None:
                    raise NotFoundError
                documents_repo.delete(doc_id)

        retry_on_concurrent_update(_delete)
