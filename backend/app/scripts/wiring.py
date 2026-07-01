"""DI wiring for the Lambda composition root (spec §8.6) — the testable assembly.

``build()`` constructs the full dependency graph and is run once on cold start by ``bootstrap.py``.
Kept in its own module (with no import-time side effects) so unit tests can import ``Container`` /
``make_email_sender`` / ``check_embedder_ceiling`` without triggering a real cold-start build.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from application.ports.email import EmailSender
from application.ports.embedding import EmbeddingModel
from application.ports.ingestion import FileParser, TextChunker
from application.ports.llm import LLMClient
from application.ports.magic_link import MagicLinkGenerator
from application.ports.rate import RateLimiter
from application.ports.repos import ChunksRepo, GuidebooksRepo, LeadsRepo, SampleBudgetRepo
from application.ports.uow import UnitOfWork
from application.ports.vector import VectorSearch
from application.use_cases.capture_lead import CaptureLeadUseCase
from application.use_cases.generate_response import GenerateResponseUseCase
from application.use_cases.resolve_magic_link import ResolveMagicLinkUseCase
from application.use_cases.sample_generate import SampleGenerateUseCase
from application.use_cases.upload_guidebook import UploadGuidebookUseCase
from config.config import Settings
from infrastructure.common.url_safe_magic_link_generator import UrlSafeMagicLinkGenerator
from infrastructure.db.sqlalchemy.postgres_chunks_repo import PostgresChunksRepo
from infrastructure.db.sqlalchemy.postgres_guidebooks_repo import PostgresGuidebooksRepo
from infrastructure.db.sqlalchemy.postgres_leads_repo import PostgresLeadsRepo
from infrastructure.db.sqlalchemy.postgres_rate_limiter import PostgresRateLimiter
from infrastructure.db.sqlalchemy.postgres_sample_budget_repo import PostgresSampleBudgetRepo
from infrastructure.db.sqlalchemy.postgres_uow import PostgresUnitOfWork
from infrastructure.email.resend_email_sender import ResendEmailSender
from infrastructure.email.smtp_email_sender import SmtpEmailSender
from infrastructure.embedding.fastembed_embedding_model import FastEmbedEmbeddingModel
from infrastructure.ingestion.composite_file_parser import CompositeFileParser
from infrastructure.ingestion.recursive_text_chunker import RecursiveTextChunker
from infrastructure.llm.anthropic_llm_client import AnthropicLLMClient
from infrastructure.sample.preload import load_sample_chunks
from infrastructure.sample.source import (
    FileSampleGuidebookSource,
    S3SampleGuidebookSource,
    SampleGuidebookSource,
    make_s3_client,
)
from infrastructure.vector.numpy_vector_search import NumpyVectorSearch


@dataclass
class Container:
    """Cold-start dependency graph for the request Lambda (spec §8.6)."""

    settings: Settings
    uow: UnitOfWork
    guidebooks_repo: GuidebooksRepo
    chunks_repo: ChunksRepo
    leads_repo: LeadsRepo
    sample_budget_repo: SampleBudgetRepo
    rate: RateLimiter
    email_sender: EmailSender
    magic_link_gen: MagicLinkGenerator
    llm: LLMClient
    embedder: EmbeddingModel
    vector_search: VectorSearch
    parser: FileParser
    chunker: TextChunker
    sample_generate: SampleGenerateUseCase
    capture_lead: CaptureLeadUseCase
    resolve_magic_link: ResolveMagicLinkUseCase
    upload_guidebook: UploadGuidebookUseCase
    generate_response: GenerateResponseUseCase


def make_email_sender(settings: Settings) -> EmailSender:
    """Select the email adapter by env: dev → SMTP/Mailpit, staging|prod → Resend (C-7).

    Dev SMTP host/port come from ``SMTP_HOST`` / ``SMTP_PORT`` env vars (defaults localhost:1025) —
    intentionally not ``Settings`` fields, to keep the prod schema clean.
    """
    if settings.env == "dev":
        return SmtpEmailSender(
            host=os.environ.get("SMTP_HOST", "localhost"),
            port=int(os.environ.get("SMTP_PORT", "1025")),
            from_address=settings.resend_from,
            magic_link_base_url=settings.magic_link_base_url,
            magic_link_url_param=settings.magic_link_url_param,
        )
    return ResendEmailSender(
        api_key=settings.resend_api_key,
        from_address=settings.resend_from,
        magic_link_base_url=settings.magic_link_base_url,
        magic_link_url_param=settings.magic_link_url_param,
        timeout_seconds=settings.email_timeout_seconds,
    )


def make_sample_source(settings: Settings) -> SampleGuidebookSource:
    """Select the sample-guidebook source by env: dev → local file, staging|prod → S3 (#5 / §8.6).

    The sample is business content; staging/prod read it from S3 so it is updatable without a redeploy.
    The source params are env-specific Nullable ``Settings`` fields — each env sets only the one it uses:
    dev → ``sample_guidebook_path``; staging/prod → ``sample_guidebook_s3_bucket`` / ``_key`` +
    ``aws_resources_region`` (Terraform-injected). ``AWS_RESOURCES_REGION`` is also read raw in the bootstrap
    for the pre-Settings Secrets Manager client.

    :raises ValueError: if the selected env is missing its sample-source params.
    """
    if settings.env == "dev":
        path = settings.sample_guidebook_path
        if path is None:
            raise ValueError("sample_guidebook_path is required for dev")
        return FileSampleGuidebookSource(path)
    region = settings.aws_resources_region
    bucket = settings.sample_guidebook_s3_bucket
    key = settings.sample_guidebook_s3_key
    if region is None or bucket is None or key is None:
        raise ValueError(
            "aws_resources_region + sample_guidebook_s3_bucket/_key are required for staging/prod"
        )
    return S3SampleGuidebookSource(make_s3_client(region), bucket=bucket, key=key)


def check_embedder_ceiling(settings: Settings, embedder: FastEmbedEmbeddingModel) -> None:
    """Fail fast if ``max_chunk_tokens`` exceeds the embedder's real token ceiling (§2.5 / C-11).

    The ``Settings`` validator cannot load the model, so this composition-root guard is the seam
    that catches a config that would silently truncate over-long chunks.

    :raises ValueError: if ``settings.max_chunk_tokens > embedder.max_input_tokens()``.
    """
    ceiling = embedder.max_input_tokens()
    if settings.max_chunk_tokens > ceiling:
        raise ValueError(
            f"max_chunk_tokens={settings.max_chunk_tokens} exceeds embedder ceiling {ceiling}"
        )


def build() -> Container:
    """Construct the full Lambda dependency graph (spec §8.6). Runs once per cold start."""
    settings = Settings.from_env()
    uow = PostgresUnitOfWork(settings.database_url)
    guidebooks_repo = PostgresGuidebooksRepo(uow)
    chunks_repo = PostgresChunksRepo(uow)
    leads_repo = PostgresLeadsRepo(uow)
    sample_budget_repo = PostgresSampleBudgetRepo(uow)
    rate = PostgresRateLimiter(uow, settings)
    email_sender = make_email_sender(settings)
    magic_link_gen = UrlSafeMagicLinkGenerator(settings.magic_link_token_bytes)
    llm = AnthropicLLMClient(
        base_url=settings.anthropic_base_url, timeout_seconds=settings.llm_timeout_seconds
    )
    embedder = FastEmbedEmbeddingModel(settings.embedding_model_name)
    check_embedder_ceiling(settings, embedder)
    vector_search = NumpyVectorSearch()
    parser = CompositeFileParser()
    chunker = RecursiveTextChunker(
        length_function=embedder.count_tokens,
        chunk_window=settings.chunk_window,
        chunk_overlap=settings.chunk_overlap,
    )
    sample_source = make_sample_source(settings)
    sample_chunks = load_sample_chunks(sample_source, parser, chunker, embedder)
    return Container(
        settings=settings,
        uow=uow,
        guidebooks_repo=guidebooks_repo,
        chunks_repo=chunks_repo,
        leads_repo=leads_repo,
        sample_budget_repo=sample_budget_repo,
        rate=rate,
        email_sender=email_sender,
        magic_link_gen=magic_link_gen,
        llm=llm,
        embedder=embedder,
        vector_search=vector_search,
        parser=parser,
        chunker=chunker,
        sample_generate=SampleGenerateUseCase(
            rate, sample_budget_repo, embedder, vector_search, llm, uow, sample_chunks, settings
        ),
        capture_lead=CaptureLeadUseCase(
            rate, leads_repo, email_sender, magic_link_gen, uow, settings
        ),
        resolve_magic_link=ResolveMagicLinkUseCase(
            rate, leads_repo, guidebooks_repo, uow, settings
        ),
        upload_guidebook=UploadGuidebookUseCase(
            rate, leads_repo, guidebooks_repo, chunks_repo, parser, chunker, embedder, uow, settings
        ),
        generate_response=GenerateResponseUseCase(
            rate,
            leads_repo,
            guidebooks_repo,
            chunks_repo,
            embedder,
            vector_search,
            llm,
            uow,
            settings,
        ),
    )
