"""The command line: arguments in; a result and an exit code out.

stdout carries the result alone — a `document_id`, an answer's text — or, with `--json`, exactly one
JSON object; diagnostics go to stderr. Every class of failure has its own exit code (`EXIT_CODES`),
so a script tells "nothing in the document" from "no such document" without reading prose. `2` is
Click's own, for a malformed command line: it is refused before any command runs — and so before
`--json` can shape the output.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, NoReturn

import httpx
import typer

from guest_reply import flows
from guest_reply.clients import documents, generation
from guest_reply.clients.auth import StaticToken
from guest_reply.clients.http import ServiceCaller
from guest_reply.config import load_settings
from guest_reply.errors import (
    CleanupFailure,
    ConfigurationError,
    DocumentNotFoundError,
    FileUnreadableError,
    GuestReplyError,
    LimitReachedError,
    ProviderUnavailableError,
    RequestRejectedError,
    ServiceUnreachableError,
    TokenRejectedError,
    UnexpectedResponseError,
)

EXIT_NO_CONTEXT = 5
"""Not success: "no answer, because the document has nothing on it" must not read as an answer."""

EXIT_CODES: dict[type[GuestReplyError], int] = {
    ConfigurationError: 1,
    FileUnreadableError: 3,
    DocumentNotFoundError: 4,
    LimitReachedError: 6,
    ProviderUnavailableError: 7,
    ServiceUnreachableError: 8,
    UnexpectedResponseError: 9,
    TokenRejectedError: 10,
    RequestRejectedError: 11,
}

app = typer.Typer(
    help="Answer a guest's message from a guidebook, through rag-documents and llm-client.",
    no_args_is_help=True,
    add_completion=False,
    # Click's plain messages: scripts read the output as well as people.
    rich_markup_mode=None,
    # A pretty traceback prints every frame's locals — the token among them.
    pretty_exceptions_enable=False,
)

JsonOption = Annotated[bool, typer.Option("--json", help="Print one JSON object instead of text.")]
NameOption = Annotated[str | None, typer.Option("--name", help="The document's display name.")]
FileArgument = Annotated[Path, typer.Argument(help="The guidebook file, sent as is.")]
DocumentIdArgument = Annotated[uuid.UUID, typer.Argument(help="The document's id.")]


@app.command()
def ingest(file: FileArgument, name: NameOption = None, json_output: JsonOption = False) -> None:
    """Upload a guidebook and print its document_id. The name defaults to the file's."""
    with _command(json_output) as run:
        created = flows.ingest(run.services(), file, name)
        run.emit(created.document_id, _created(created))


@app.command()
def replace(
    document_id: DocumentIdArgument,
    file: FileArgument,
    name: NameOption = None,
    json_output: JsonOption = False,
) -> None:
    """Replace a document's content in one call; the document_id stays, and so does the name
    unless --name is given."""
    with _command(json_output) as run:
        created = flows.replace(run.services(), str(document_id), file, name)
        run.emit(created.document_id, _created(created))


@app.command()
def ask(
    arguments: Annotated[
        list[str],
        typer.Argument(
            metavar="[DOCUMENT_ID] GUEST_MESSAGE",
            help="The stored document to answer from, then the guest's message.",
        ),
    ],
    file: Annotated[
        Path | None,
        typer.Option(
            "--file",
            help="One-shot: upload this file, answer, delete the document. Replaces DOCUMENT_ID.",
        ),
    ] = None,
    json_output: JsonOption = False,
) -> None:
    """Answer a guest's message from a stored document — or from a file, leaving nothing behind."""
    source, guest_message = _ask_arguments(arguments, file)
    with _command(json_output) as run:
        services = run.services()
        if isinstance(source, Path):
            shot = flows.ask_from_file(services, source, guest_message)
            run.answer(shot.answer, shot.document_id, cleanup_failure=shot.cleanup_failure)
        else:
            run.answer(flows.ask(services, source, guest_message), source)


@app.command("rm")
def remove(document_id: DocumentIdArgument, json_output: JsonOption = False) -> None:
    """Delete a document. A missing one is an error (exit 4), not a success."""
    with _command(json_output) as run:
        flows.remove(run.services(), str(document_id))
        run.emit(None, {"document_id": str(document_id), "deleted": True})


class _Run:
    """One command's run: its request id, how it prints, and the clients it calls with."""

    def __init__(self, json_output: bool, http: httpx.Client) -> None:
        self._json_output = json_output
        self._http = http
        # New for every run and shared by all its calls: what finds this run in both services' logs.
        self._request_id = uuid.uuid4().hex

    def services(self) -> flows.Services:
        """Read the configuration and build the clients — before any network call.

        :raises ConfigurationError:
        """
        settings = load_settings()
        token = StaticToken(settings.token)

        def caller(origin: str, api_base: str) -> ServiceCaller:
            return ServiceCaller(
                self._http,
                origin=origin,
                api_base=api_base,
                token=token,
                request_id=self._request_id,
                on_wait=_announce_wait,
            )

        return flows.Services(
            documents=documents.DocumentsClient(
                caller(settings.rag_documents_url, documents.API_BASE)
            ),
            generation=generation.GenerationClient(
                caller(settings.llm_client_url, generation.API_BASE)
            ),
            model_alias=settings.model_alias,
        )

    def emit(self, text: str | None, body: dict[str, object]) -> None:
        """The result: `text` on stdout, or `body` as the one JSON object."""
        if self._json_output:
            _print_json({**body, "request_id": self._request_id})
        elif text is not None:
            typer.echo(text)

    def answer(
        self,
        answer: flows.Answer | None,
        document_id: str,
        *,
        cleanup_failure: CleanupFailure | None = None,
    ) -> None:
        body: dict[str, object]
        if answer is None:
            body = {"answer": None, "chunks_used": 0, "document_id": document_id}
        else:
            body = {
                "answer": answer.text,
                "chunks_used": answer.chunks_used,
                "usage": answer.usage.model_dump(),
                "provider": answer.provider,
                "model": answer.model,
                "document_id": document_id,
            }
        if cleanup_failure is not None:
            body["cleanup_error"] = _cleanup_object(cleanup_failure)
        self.emit(None if answer is None else answer.text, body)
        if answer is None and not self._json_output:
            typer.echo(
                "there is no relevant context in the document — generation was not called",
                err=True,
            )
        if cleanup_failure is not None:
            # A document left behind is the one-shot's broken promise: the command fails with it.
            _warn(cleanup_failure)
            raise typer.Exit(EXIT_CODES[type(cleanup_failure.error)])
        if answer is None:
            raise typer.Exit(EXIT_NO_CONTEXT)

    def fail(self, error: GuestReplyError) -> NoReturn:
        if self._json_output:
            body: dict[str, object] = {"error": _error_object(error)}
            if error.cleanup_failure is not None:
                body["cleanup_error"] = _cleanup_object(error.cleanup_failure)
            _print_json({**body, "request_id": self._request_id})
        else:
            typer.echo(_describe(error), err=True)
        if error.cleanup_failure is not None:
            _warn(error.cleanup_failure)
        raise typer.Exit(EXIT_CODES[type(error)])


@contextmanager
def _command(json_output: bool) -> Iterator[_Run]:
    with httpx.Client() as http:
        run = _Run(json_output, http)
        try:
            yield run
        except GuestReplyError as error:
            run.fail(error)


def _ask_arguments(arguments: list[str], file: Path | None) -> tuple[Path | str, str]:
    """(the file or the document_id, the guest's message). --file and DOCUMENT_ID exclude each
    other."""
    if file is not None:
        if len(arguments) != 1:
            raise typer.BadParameter(
                "--file and DOCUMENT_ID are mutually exclusive: give --file FILE GUEST_MESSAGE"
            )
        return file, arguments[0]
    if len(arguments) != 2:
        raise typer.BadParameter(
            "give DOCUMENT_ID GUEST_MESSAGE, or --file FILE GUEST_MESSAGE for a one-shot"
        )
    return _document_id(arguments[0]), arguments[1]


def _document_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise typer.BadParameter(f"{value!r} is not a document id (a UUID)") from None


def _created(created: documents.CreatedDocument) -> dict[str, object]:
    return {"document_id": created.document_id, "chunk_count": created.chunk_count}


def _error_object(error: GuestReplyError) -> dict[str, object]:
    return {"code": error.code, "message": error.message, "details": error.details}


def _cleanup_object(failure: CleanupFailure) -> dict[str, object]:
    return {"document_id": failure.document_id, "error": _error_object(failure.error)}


def _describe(error: GuestReplyError) -> str:
    head = f"error: {error.code}: {error.message}" if error.message else f"error: {error.code}"
    details = (f"  {key}: {_plain(value)}" for key, value in error.details.items())
    return "\n".join([head, *details])


def _plain(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _warn(failure: CleanupFailure) -> None:
    typer.echo(
        f"warning: the temporary document {failure.document_id} was not deleted — "
        f"remove it with: guest-reply rm {failure.document_id}",
        err=True,
    )
    typer.echo(_describe(failure.error), err=True)


def _announce_wait(seconds: int) -> None:
    typer.echo(f"rate limited: waiting {seconds} s, then repeating the call", err=True)


def _print_json(body: dict[str, object]) -> None:
    typer.echo(json.dumps(body, ensure_ascii=False))
