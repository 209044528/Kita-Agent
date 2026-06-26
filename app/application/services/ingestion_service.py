from __future__ import annotations

import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from app.application.services.document_parser_service import DocumentParserService
from app.application.services.knowledge_app_service import KnowledgeAppService
from app.core.input_security import validate_git_url, validate_upload_content, validate_upload_name
from app.core.security import RequestIdentity
from app.domain.knowledge.repository import DocumentEntity
from app.infrastructure.platform_store import PlatformStore


@dataclass
class IngestionRequest:
    kind: str
    user_id: str = "anonymous"
    tag: str | None = None
    source_name: str | None = None
    raw_text: str | None = None
    file_bytes: bytes | None = None
    filename: str | None = None
    repo_url: str | None = None
    branch: str = "main"
    knowledge_dir: str | None = None
    visibility: str = "public"
    allowed_user_ids: list[str] = field(default_factory=list)


@dataclass
class IngestionState:
    job_id: str
    request: IngestionRequest
    identity: RequestIdentity
    raw_text: str = ""
    documents: list[DocumentEntity] = field(default_factory=list)
    source_type: str = "text"


@dataclass(frozen=True)
class IngestionNode:
    name: str
    handler: Callable[[IngestionState], dict[str, Any] | None]
    depends_on: tuple[str, ...] = ()


class IngestionPipeline:
    """Node-based ingestion pipeline with persistent job and node logs.

    The first version keeps a built-in DAG per source kind. It is intentionally
    small, but the node boundary mirrors ragent's Fetcher/Parser/Chunker/Enricher/
    Indexer design so a future admin UI can make these definitions configurable.
    """

    def __init__(
        self,
        knowledge_service: KnowledgeAppService,
        store: PlatformStore,
        *,
        parser: type[DocumentParserService] = DocumentParserService,
    ):
        self.knowledge_service = knowledge_service
        self.store = store
        self.parser = parser

    def submit(self, request: IngestionRequest, identity: RequestIdentity) -> str:
        request = self._validate_request(request)
        request.user_id = identity.user_id
        job_id = uuid.uuid4().hex
        self.store.create_ingest_job(
            {
                "job_id": job_id,
                "kind": request.kind,
                "status": "queued",
                "user_id": identity.user_id,
                "tag": request.tag,
                "source_name": request.source_name or request.filename or request.repo_url,
                "knowledge_dir": request.knowledge_dir,
                "visibility": request.visibility,
                "request": self._request_preview(request),
                "stats": {"stage": "queued", "pipeline": self.pipeline_definition(request.kind)},
            }
        )
        return job_id

    def run(self, job_id: str, request: IngestionRequest, identity: RequestIdentity) -> None:
        request.user_id = identity.user_id
        state = IngestionState(job_id=job_id, request=request, identity=identity)
        stats: dict[str, Any] = {
            "stage": "started",
            "pipeline": self.pipeline_definition(request.kind),
            "nodes": [],
        }
        self.store.update_ingest_job(job_id, status="running", stats=stats, started=True)
        try:
            completed: set[str] = set()
            for node in self._nodes(request.kind):
                missing = [dep for dep in node.depends_on if dep not in completed]
                if missing:
                    raise RuntimeError(
                        f"Ingestion node {node.name} is missing dependencies: {missing}"
                    )

                stats["stage"] = node.name
                self.store.update_ingest_job(job_id, status="running", stats=stats)
                output = self._run_node(job_id, node, state)
                completed.add(node.name)
                stats["nodes"].append({"name": node.name, "status": "succeeded"})
                if output:
                    stats.update(output)

            self.store.update_ingest_job(
                job_id,
                status="succeeded",
                stats={**stats, "stage": "finished"},
                finished=True,
            )
        except Exception as exc:
            logger.exception("Ingest job {} failed", job_id)
            self.store.update_ingest_job(
                job_id,
                status="failed",
                stats={**stats, "stage": "failed"},
                error=str(exc),
                finished=True,
            )

    def pipeline_definition(self, kind: str) -> dict[str, Any]:
        return {
            "kind": kind,
            "nodes": [
                {"name": node.name, "depends_on": list(node.depends_on)}
                for node in self._nodes(kind)
            ],
        }

    def _nodes(self, kind: str) -> list[IngestionNode]:
        if kind == "git":
            return [
                IngestionNode("validate", self._validate_node),
                IngestionNode("fetch_git", self._fetch_git_node, ("validate",)),
                IngestionNode("parse_git", self._parse_git_node, ("fetch_git",)),
                IngestionNode("enrich", self._enrich_node, ("parse_git",)),
                IngestionNode("index", self._index_node, ("enrich",)),
            ]

        parse_node = (
            IngestionNode("parse_file", self._parse_file_node, ("validate",))
            if kind == "file"
            else IngestionNode("parse_text", self._parse_text_node, ("validate",))
        )
        return [
            IngestionNode("validate", self._validate_node),
            parse_node,
            IngestionNode("chunk", self._chunk_text_node, (parse_node.name,)),
            IngestionNode("enrich", self._enrich_node, ("chunk",)),
            IngestionNode("index", self._index_node, ("enrich",)),
        ]

    def _run_node(
        self, job_id: str, node: IngestionNode, state: IngestionState
    ) -> dict[str, Any] | None:
        input_payload = {
            "kind": state.request.kind,
            "tag": state.request.tag,
            "source": state.request.source_name
            or state.request.filename
            or state.request.repo_url,
            "document_count": len(state.documents),
        }
        log_id = self.store.start_ingestion_node(job_id, node.name, input_payload)
        started = time.perf_counter()
        try:
            output = node.handler(state) or {}
            self.store.finish_ingestion_node(
                log_id,
                status="succeeded",
                output_payload=output,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            return output
        except Exception as exc:
            self.store.finish_ingestion_node(
                log_id,
                status="failed",
                output_payload={},
                error=str(exc),
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            raise

    def _validate_node(self, state: IngestionState) -> dict[str, Any]:
        request = self._validate_request(state.request)
        if request.kind == "git":
            request.repo_url = validate_git_url(request.repo_url or "")
        elif request.kind == "file":
            request.filename = validate_upload_name(request.filename or "")
            validate_upload_content(request.filename, request.file_bytes or b"")
        return {
            "validated": True,
            "visibility": request.visibility,
            "knowledge_dir": request.knowledge_dir,
        }

    def _parse_text_node(self, state: IngestionState) -> dict[str, Any]:
        state.raw_text = (state.request.raw_text or "").strip()
        state.source_type = "text"
        return {"text_length": len(state.raw_text), "source_type": state.source_type}

    def _parse_file_node(self, state: IngestionState) -> dict[str, Any]:
        filename = state.request.filename or ""
        suffix = Path(filename).suffix
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as file:
                file.write(state.request.file_bytes or b"")
                tmp_path = file.name
            state.raw_text = self.parser.parse_document_to_text(tmp_path)
            state.source_type = "file"
            return {
                "text_length": len(state.raw_text),
                "source_type": state.source_type,
                "filename": filename,
            }
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

    def _fetch_git_node(self, state: IngestionState) -> dict[str, Any]:
        return {
            "repo_url": state.request.repo_url,
            "branch": state.request.branch or "main",
        }

    def _parse_git_node(self, state: IngestionState) -> dict[str, Any]:
        state.documents = self.knowledge_service.build_documents_from_git(
            repo_url=state.request.repo_url or "",
            branch=state.request.branch or "main",
            knowledge_tag=state.request.tag,
            user_id=state.identity.user_id,
            visibility=state.request.visibility,
            allowed_user_ids=state.request.allowed_user_ids,
            knowledge_dir=state.request.knowledge_dir,
        )
        state.source_type = "git"
        return {
            "source_type": state.source_type,
            "chunk_count": len(state.documents),
            "document_count": self._document_count(state.documents),
        }

    def _chunk_text_node(self, state: IngestionState) -> dict[str, Any]:
        state.documents = self.knowledge_service.build_documents_from_text(
            raw_text=state.raw_text,
            tag=state.request.tag or "default",
            source_name=state.request.source_name
            or state.request.filename
            or "manual",
            user_id=state.identity.user_id,
            visibility=state.request.visibility,
            allowed_user_ids=state.request.allowed_user_ids,
            knowledge_dir=state.request.knowledge_dir,
        )
        return {
            "chunk_count": len(state.documents),
            "document_count": self._document_count(state.documents),
        }

    def _enrich_node(self, state: IngestionState) -> dict[str, Any]:
        kb_id = self.store.make_kb_id(
            state.request.tag or self._fallback_git_tag(state.request),
            state.request.knowledge_dir,
        )
        for doc in state.documents:
            doc.metadata["kb_id"] = kb_id
            doc.metadata["ingest_job_id"] = state.job_id
            doc.metadata["source_type"] = doc.metadata.get("source_type") or state.source_type
        return {"kb_id": kb_id, "enriched": True}

    def _index_node(self, state: IngestionState) -> dict[str, Any]:
        self.knowledge_service.store_documents(state.documents)
        self._write_catalog(state)
        return {
            "stored": True,
            "chunk_count": len(state.documents),
            "document_count": self._document_count(state.documents),
        }

    def _write_catalog(self, state: IngestionState) -> None:
        if not state.documents:
            return
        tag = state.request.tag or self._fallback_git_tag(state.request)
        kb_id = self.store.upsert_knowledge_base(
            tag=tag,
            name=tag,
            knowledge_dir=state.request.knowledge_dir,
            visibility=state.request.visibility,
            owner_user_id=state.identity.user_id,
            allowed_user_ids=state.request.allowed_user_ids,
            metadata={
                "last_ingest_job_id": state.job_id,
                "source_type": state.source_type,
            },
        )

        by_document: dict[str, list[DocumentEntity]] = {}
        for doc in state.documents:
            document_id = str(doc.metadata.get("document_id") or doc.id)
            by_document.setdefault(document_id, []).append(doc)

        chunk_rows: list[dict[str, Any]] = []
        for document_id, docs in by_document.items():
            first = docs[0]
            metadata = dict(first.metadata or {})
            source_name = str(
                metadata.get("source_name")
                or metadata.get("source")
                or state.request.source_name
                or state.request.filename
                or state.request.repo_url
                or "manual"
            )
            source_type = str(metadata.get("source_type") or state.source_type)
            self.store.upsert_knowledge_document(
                document_id=document_id,
                kb_id=kb_id,
                tag=tag,
                source_name=source_name,
                source_type=source_type,
                knowledge_dir=state.request.knowledge_dir,
                visibility=state.request.visibility,
                owner_user_id=state.identity.user_id,
                metadata={
                    **metadata,
                    "chunk_count": len(docs),
                    "last_ingest_job_id": state.job_id,
                },
            )
            for doc in docs:
                chunk_rows.append(
                    {
                        "chunk_id": doc.id or str(doc.metadata.get("chunk_hash")),
                        "document_id": document_id,
                        "kb_id": kb_id,
                        "tag": tag,
                        "source_name": source_name,
                        "chunk_index": doc.metadata.get("chunk_index"),
                        "content_preview": doc.content[:500],
                        "metadata": doc.metadata,
                    }
                )

        self.store.upsert_knowledge_chunks(chunks=chunk_rows)

    def _document_count(self, documents: list[DocumentEntity]) -> int:
        return len({doc.metadata.get("document_id") or doc.id for doc in documents})

    def _validate_request(self, request: IngestionRequest) -> IngestionRequest:
        if request.visibility not in {"public", "private"}:
            raise ValueError("visibility must be public or private")
        if request.kind not in {"text", "file", "git"}:
            raise ValueError("kind must be text, file, or git")
        if request.kind == "text" and not request.raw_text:
            raise ValueError("raw_text is required for text ingestion")
        if request.kind == "file" and (not request.file_bytes or not request.filename):
            raise ValueError("file_bytes and filename are required for file ingestion")
        if request.kind == "git" and not request.repo_url:
            raise ValueError("repo_url is required for git ingestion")
        if request.kind != "git" and not request.tag:
            raise ValueError("tag is required")
        return request

    def _fallback_git_tag(self, request: IngestionRequest) -> str:
        if request.tag:
            return request.tag
        clean_url = (request.repo_url or "git").rstrip("/").replace(".git", "")
        if "github.com" in clean_url and ("/tree/" in clean_url or "/blob/" in clean_url):
            clean_url = clean_url.split("/tree/")[0].split("/blob/")[0]
        return clean_url.split("/")[-1] or "git"

    def _request_preview(self, request: IngestionRequest) -> dict[str, Any]:
        return {
            "kind": request.kind,
            "tag": request.tag,
            "source_name": request.source_name,
            "filename": request.filename,
            "repo_url": request.repo_url,
            "branch": request.branch,
            "knowledge_dir": request.knowledge_dir,
            "visibility": request.visibility,
            "raw_text_length": len(request.raw_text or ""),
            "file_size": len(request.file_bytes or b""),
        }
