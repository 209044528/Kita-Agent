from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(*parts: Any, prefix: str = "") -> str:
    digest = hashlib.sha1(
        "::".join("" if part is None else str(part) for part in parts).encode("utf-8")
    ).hexdigest()
    return f"{prefix}{digest}" if prefix else digest


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _json_loads(value: str | bytes | None, default: Any = None) -> Any:
    if value in (None, ""):
        return {} if default is None else default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {} if default is None else default


class PlatformStore:
    """SQLite store for platform-level state.

    pgvector remains the source of truth for vector retrieval. This store keeps
    product/platform metadata: ingest orchestration, node logs, knowledge catalog,
    intent routing, trace feedback, eval datasets, and model health/configuration.
    """

    def __init__(self, db_path: str):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS ingest_jobs (
                    job_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    tag TEXT,
                    source_name TEXT,
                    knowledge_dir TEXT,
                    visibility TEXT,
                    request_json TEXT NOT NULL,
                    stats_json TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_ingest_jobs_user_created
                    ON ingest_jobs(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_ingest_jobs_status
                    ON ingest_jobs(status);

                CREATE TABLE IF NOT EXISTS ingestion_node_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    node_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    output_json TEXT NOT NULL,
                    error TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    duration_ms REAL,
                    FOREIGN KEY(job_id) REFERENCES ingest_jobs(job_id)
                );

                CREATE INDEX IF NOT EXISTS idx_ingestion_node_logs_job
                    ON ingestion_node_logs(job_id, id);

                CREATE TABLE IF NOT EXISTS knowledge_bases (
                    kb_id TEXT PRIMARY KEY,
                    tag TEXT NOT NULL,
                    name TEXT NOT NULL,
                    knowledge_dir TEXT,
                    visibility TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    allowed_user_ids_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_knowledge_bases_tag
                    ON knowledge_bases(tag);
                CREATE INDEX IF NOT EXISTS idx_knowledge_bases_owner
                    ON knowledge_bases(owner_user_id);

                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    document_id TEXT PRIMARY KEY,
                    kb_id TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    knowledge_dir TEXT,
                    visibility TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(kb_id) REFERENCES knowledge_bases(kb_id)
                );

                CREATE INDEX IF NOT EXISTS idx_knowledge_documents_kb
                    ON knowledge_documents(kb_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    kb_id TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    chunk_index INTEGER,
                    content_preview TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES knowledge_documents(document_id)
                );

                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document
                    ON knowledge_chunks(document_id, chunk_index);
                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_kb
                    ON knowledge_chunks(kb_id);

                CREATE TABLE IF NOT EXISTS intent_nodes (
                    node_id TEXT PRIMARY KEY,
                    parent_id TEXT,
                    name TEXT NOT NULL,
                    description TEXT,
                    kind TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    priority INTEGER NOT NULL,
                    keywords_json TEXT NOT NULL,
                    knowledge_tag TEXT,
                    knowledge_dir TEXT,
                    mcp_server TEXT,
                    mcp_tool TEXT,
                    prompt_template TEXT,
                    top_k INTEGER,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_intent_nodes_enabled
                    ON intent_nodes(enabled, priority DESC);

                CREATE TABLE IF NOT EXISTS query_term_mappings (
                    mapping_id TEXT PRIMARY KEY,
                    source_term TEXT NOT NULL,
                    target_term TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_query_term_mappings_enabled
                    ON query_term_mappings(enabled);

                CREATE TABLE IF NOT EXISTS trace_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    trace_id TEXT,
                    session_id TEXT,
                    event_type TEXT NOT NULL,
                    step INTEGER,
                    duration_ms REAL,
                    success INTEGER,
                    payload_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_trace_events_trace
                    ON trace_events(trace_id, id);
                CREATE INDEX IF NOT EXISTS idx_trace_events_session
                    ON trace_events(session_id, id);

                CREATE TABLE IF NOT EXISTS bad_cases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    category TEXT NOT NULL,
                    session_id TEXT,
                    trace_id TEXT,
                    input_text TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    model_output TEXT
                );

                CREATE TABLE IF NOT EXISTS trace_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    trace_id TEXT,
                    session_id TEXT,
                    user_id TEXT NOT NULL,
                    rating INTEGER,
                    category TEXT,
                    comment TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_trace_feedback_trace
                    ON trace_feedback(trace_id, id);

                CREATE TABLE IF NOT EXISTS eval_datasets (
                    dataset_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS eval_cases (
                    case_id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    query TEXT NOT NULL,
                    expected_keywords_json TEXT NOT NULL,
                    tag TEXT,
                    must_not_contain_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(dataset_id) REFERENCES eval_datasets(dataset_id)
                );

                CREATE INDEX IF NOT EXISTS idx_eval_cases_dataset
                    ON eval_cases(dataset_id, created_at);

                CREATE TABLE IF NOT EXISTS model_configs (
                    model_name TEXT PRIMARY KEY,
                    provider TEXT,
                    enabled INTEGER NOT NULL,
                    priority INTEGER NOT NULL,
                    options_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS model_health (
                    model_name TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    failures INTEGER NOT NULL,
                    open_until REAL,
                    last_success_at TEXT,
                    last_failure_at TEXT,
                    last_error TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )

    # ------------------------------------------------------------------
    # Ingestion jobs and node logs
    # ------------------------------------------------------------------

    def create_ingest_job(self, job: dict[str, Any]) -> None:
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ingest_jobs (
                    job_id, kind, status, user_id, tag, source_name, knowledge_dir,
                    visibility, request_json, stats_json, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job["job_id"],
                    job["kind"],
                    job.get("status", "queued"),
                    job["user_id"],
                    job.get("tag"),
                    job.get("source_name"),
                    job.get("knowledge_dir"),
                    job.get("visibility", "public"),
                    _json_dumps(job.get("request", {})),
                    _json_dumps(job.get("stats", {})),
                    job.get("error"),
                    now,
                    now,
                ),
            )

    def update_ingest_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        stats: dict[str, Any] | None = None,
        error: str | None = None,
        started: bool = False,
        finished: bool = False,
    ) -> None:
        now = utc_now()
        assignments = ["updated_at = ?"]
        values: list[Any] = [now]
        if status is not None:
            assignments.append("status = ?")
            values.append(status)
        if stats is not None:
            assignments.append("stats_json = ?")
            values.append(_json_dumps(stats))
        if error is not None:
            assignments.append("error = ?")
            values.append(error)
        if started:
            assignments.append("started_at = COALESCE(started_at, ?)")
            values.append(now)
        if finished:
            assignments.append("finished_at = ?")
            values.append(now)
        values.append(job_id)
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE ingest_jobs SET {', '.join(assignments)} WHERE job_id = ?",
                values,
            )

    def get_ingest_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ingest_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._decode_job(row) if row else None

    def list_ingest_jobs(
        self, *, user_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM ingest_jobs"
        params: list[Any] = []
        if user_id:
            sql += " WHERE user_id = ?"
            params.append(user_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._decode_job(row) for row in rows]

    def start_ingestion_node(
        self, job_id: str, node_name: str, input_payload: dict[str, Any] | None = None
    ) -> int:
        now = utc_now()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ingestion_node_logs (
                    job_id, node_name, status, input_json, output_json, started_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    node_name,
                    "running",
                    _json_dumps(input_payload or {}),
                    _json_dumps({}),
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def finish_ingestion_node(
        self,
        log_id: int,
        *,
        status: str,
        output_payload: dict[str, Any] | None = None,
        error: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE ingestion_node_logs
                SET status = ?, output_json = ?, error = ?, finished_at = ?,
                    duration_ms = ?
                WHERE id = ?
                """,
                (
                    status,
                    _json_dumps(output_payload or {}),
                    error,
                    utc_now(),
                    duration_ms,
                    log_id,
                ),
            )

    def list_ingestion_node_logs(self, job_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ingestion_node_logs
                WHERE job_id = ?
                ORDER BY id
                """,
                (job_id,),
            ).fetchall()
        return [self._decode_node_log(row) for row in rows]

    # ------------------------------------------------------------------
    # Knowledge catalog
    # ------------------------------------------------------------------

    def make_kb_id(self, tag: str, knowledge_dir: str | None = None) -> str:
        return stable_id(tag, knowledge_dir or "", prefix="kb_")

    def upsert_knowledge_base(
        self,
        *,
        tag: str,
        name: str | None = None,
        knowledge_dir: str | None = None,
        visibility: str = "public",
        owner_user_id: str = "anonymous",
        allowed_user_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        kb_id = self.make_kb_id(tag, knowledge_dir)
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_bases (
                    kb_id, tag, name, knowledge_dir, visibility, owner_user_id,
                    allowed_user_ids_json, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(kb_id) DO UPDATE SET
                    name = excluded.name,
                    visibility = excluded.visibility,
                    owner_user_id = excluded.owner_user_id,
                    allowed_user_ids_json = excluded.allowed_user_ids_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    kb_id,
                    tag,
                    name or tag,
                    knowledge_dir,
                    visibility,
                    owner_user_id,
                    _json_dumps(allowed_user_ids or []),
                    _json_dumps(metadata or {}),
                    now,
                    now,
                ),
            )
        return kb_id

    def upsert_knowledge_document(
        self,
        *,
        document_id: str,
        kb_id: str,
        tag: str,
        source_name: str,
        source_type: str,
        knowledge_dir: str | None,
        visibility: str,
        owner_user_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_documents (
                    document_id, kb_id, tag, source_name, source_type, knowledge_dir,
                    visibility, owner_user_id, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    kb_id = excluded.kb_id,
                    tag = excluded.tag,
                    source_name = excluded.source_name,
                    source_type = excluded.source_type,
                    knowledge_dir = excluded.knowledge_dir,
                    visibility = excluded.visibility,
                    owner_user_id = excluded.owner_user_id,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    document_id,
                    kb_id,
                    tag,
                    source_name,
                    source_type,
                    knowledge_dir,
                    visibility,
                    owner_user_id,
                    _json_dumps(metadata or {}),
                    now,
                    now,
                ),
            )

    def upsert_knowledge_chunks(
        self,
        *,
        chunks: list[dict[str, Any]],
    ) -> None:
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO knowledge_chunks (
                    chunk_id, document_id, kb_id, tag, source_name, chunk_index,
                    content_preview, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    document_id = excluded.document_id,
                    kb_id = excluded.kb_id,
                    tag = excluded.tag,
                    source_name = excluded.source_name,
                    chunk_index = excluded.chunk_index,
                    content_preview = excluded.content_preview,
                    metadata_json = excluded.metadata_json
                """,
                [
                    (
                        chunk["chunk_id"],
                        chunk["document_id"],
                        chunk["kb_id"],
                        chunk["tag"],
                        chunk["source_name"],
                        chunk.get("chunk_index"),
                        chunk.get("content_preview", ""),
                        _json_dumps(chunk.get("metadata", {})),
                        now,
                    )
                    for chunk in chunks
                ],
            )

    def list_knowledge_bases(
        self,
        *,
        user_id: str = "anonymous",
        is_admin: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_bases ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        items = [self._decode_kb(row) for row in rows]
        return [
            item
            for item in items
            if self._passes_platform_access(item, user_id=user_id, is_admin=is_admin)
        ]

    def list_knowledge_documents(
        self,
        *,
        kb_id: str | None = None,
        tag: str | None = None,
        user_id: str = "anonymous",
        is_admin: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM knowledge_documents"
        clauses = []
        params: list[Any] = []
        if kb_id:
            clauses.append("kb_id = ?")
            params.append(kb_id)
        if tag:
            clauses.append("tag = ?")
            params.append(tag)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        items = [self._decode_document(row) for row in rows]
        return [
            item
            for item in items
            if self._passes_platform_access(item, user_id=user_id, is_admin=is_admin)
        ]

    def list_knowledge_chunks(
        self,
        *,
        document_id: str | None = None,
        kb_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM knowledge_chunks"
        clauses = []
        params: list[Any] = []
        if document_id:
            clauses.append("document_id = ?")
            params.append(document_id)
        if kb_id:
            clauses.append("kb_id = ?")
            params.append(kb_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY chunk_index LIMIT ?"
        params.append(limit)
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._decode_chunk(row) for row in rows]

    # ------------------------------------------------------------------
    # Intent routing and query term mappings
    # ------------------------------------------------------------------

    def upsert_intent_node(self, node: dict[str, Any], *, created_by: str) -> str:
        node_id = node.get("node_id") or stable_id(
            node.get("parent_id") or "", node.get("name"), node.get("kind"), prefix="intent_"
        )
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO intent_nodes (
                    node_id, parent_id, name, description, kind, enabled, priority,
                    keywords_json, knowledge_tag, knowledge_dir, mcp_server, mcp_tool,
                    prompt_template, top_k, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    parent_id = excluded.parent_id,
                    name = excluded.name,
                    description = excluded.description,
                    kind = excluded.kind,
                    enabled = excluded.enabled,
                    priority = excluded.priority,
                    keywords_json = excluded.keywords_json,
                    knowledge_tag = excluded.knowledge_tag,
                    knowledge_dir = excluded.knowledge_dir,
                    mcp_server = excluded.mcp_server,
                    mcp_tool = excluded.mcp_tool,
                    prompt_template = excluded.prompt_template,
                    top_k = excluded.top_k,
                    updated_at = excluded.updated_at
                """,
                (
                    node_id,
                    node.get("parent_id"),
                    node["name"],
                    node.get("description"),
                    node.get("kind", "KB"),
                    int(bool(node.get("enabled", True))),
                    int(node.get("priority", 0)),
                    _json_dumps(node.get("keywords", [])),
                    node.get("knowledge_tag"),
                    node.get("knowledge_dir"),
                    node.get("mcp_server"),
                    node.get("mcp_tool"),
                    node.get("prompt_template"),
                    node.get("top_k"),
                    created_by,
                    now,
                    now,
                ),
            )
        return node_id

    def list_intent_nodes(self, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM intent_nodes"
        params: list[Any] = []
        if not include_disabled:
            sql += " WHERE enabled = ?"
            params.append(1)
        sql += " ORDER BY priority DESC, updated_at DESC"
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._decode_intent(row) for row in rows]

    def delete_intent_node(self, node_id: str) -> bool:
        with self._lock, self._connect() as conn:
            result = conn.execute("DELETE FROM intent_nodes WHERE node_id = ?", (node_id,))
        return result.rowcount > 0

    def upsert_query_term_mapping(
        self,
        *,
        source_term: str,
        target_term: str,
        created_by: str,
        mapping_id: str | None = None,
        enabled: bool = True,
    ) -> str:
        mapping_id = mapping_id or stable_id(source_term.lower(), target_term.lower(), prefix="qtm_")
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO query_term_mappings (
                    mapping_id, source_term, target_term, enabled, created_by,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mapping_id) DO UPDATE SET
                    source_term = excluded.source_term,
                    target_term = excluded.target_term,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (
                    mapping_id,
                    source_term,
                    target_term,
                    int(enabled),
                    created_by,
                    now,
                    now,
                ),
            )
        return mapping_id

    def list_query_term_mappings(self, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM query_term_mappings"
        params: list[Any] = []
        if not include_disabled:
            sql += " WHERE enabled = ?"
            params.append(1)
        sql += " ORDER BY updated_at DESC"
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._decode_mapping(row) for row in rows]

    # ------------------------------------------------------------------
    # Trace, feedback, eval datasets
    # ------------------------------------------------------------------

    def insert_trace_event(self, event: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trace_events (
                    timestamp, trace_id, session_id, event_type, step, duration_ms,
                    success, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["timestamp"],
                    event.get("trace_id"),
                    event.get("session_id"),
                    event["event_type"],
                    event.get("step"),
                    event.get("duration_ms"),
                    None if event.get("success") is None else int(bool(event["success"])),
                    _json_dumps(event.get("payload", {})),
                ),
            )

    def insert_bad_case(self, case: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO bad_cases (
                    timestamp, category, session_id, trace_id, input_text, detail,
                    model_output
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case["timestamp"],
                    case["category"],
                    case.get("session_id"),
                    case.get("trace_id"),
                    case.get("input", ""),
                    case.get("detail", ""),
                    case.get("model_output"),
                ),
            )

    def read_trace_events(
        self,
        *,
        session_id: str | None = None,
        trace_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM trace_events"
        clauses = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if trace_id:
            clauses.append("trace_id = ?")
            params.append(trace_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        events = [self._decode_trace(row) for row in rows]
        return list(reversed(events))

    def read_bad_cases(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM bad_cases ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        cases = [dict(row) for row in rows]
        return list(reversed(cases))

    def trace_summary(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM trace_events").fetchone()[0]
            bad = conn.execute("SELECT COUNT(*) FROM bad_cases").fetchone()[0]
            feedback = conn.execute("SELECT COUNT(*) FROM trace_feedback").fetchone()[0]
            by_type = conn.execute(
                """
                SELECT event_type, COUNT(*) as count
                FROM trace_events
                GROUP BY event_type
                ORDER BY count DESC
                """
            ).fetchall()
        return {
            "trace_events": total,
            "bad_cases": bad,
            "feedback": feedback,
            "events_by_type": [{"event_type": row[0], "count": row[1]} for row in by_type],
        }

    def insert_trace_feedback(
        self,
        *,
        trace_id: str | None,
        session_id: str | None,
        user_id: str,
        rating: int | None = None,
        category: str | None = None,
        comment: str | None = None,
    ) -> int:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO trace_feedback (
                    timestamp, trace_id, session_id, user_id, rating, category, comment
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (utc_now(), trace_id, session_id, user_id, rating, category, comment),
            )
            return int(cursor.lastrowid)

    def read_trace_feedback(
        self, *, trace_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM trace_feedback"
        params: list[Any] = []
        if trace_id:
            sql += " WHERE trace_id = ?"
            params.append(trace_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return list(reversed([dict(row) for row in rows]))

    def create_eval_dataset(
        self, *, name: str, description: str | None, created_by: str
    ) -> str:
        dataset_id = stable_id(name, created_by, utc_now(), prefix="eval_")
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO eval_datasets (
                    dataset_id, name, description, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (dataset_id, name, description, created_by, now, now),
            )
        return dataset_id

    def list_eval_datasets(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM eval_datasets ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_eval_case(
        self,
        *,
        dataset_id: str,
        query: str,
        expected_keywords: list[str],
        tag: str | None = None,
        must_not_contain: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        case_id = stable_id(dataset_id, query, expected_keywords, utc_now(), prefix="case_")
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO eval_cases (
                    case_id, dataset_id, query, expected_keywords_json, tag,
                    must_not_contain_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    dataset_id,
                    query,
                    _json_dumps(expected_keywords),
                    tag,
                    _json_dumps(must_not_contain or []),
                    _json_dumps(metadata or {}),
                    utc_now(),
                ),
            )
            conn.execute(
                "UPDATE eval_datasets SET updated_at = ? WHERE dataset_id = ?",
                (utc_now(), dataset_id),
            )
        return case_id

    def list_eval_cases(self, dataset_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM eval_cases
                WHERE dataset_id = ?
                ORDER BY created_at
                """,
                (dataset_id,),
            ).fetchall()
        return [self._decode_eval_case(row) for row in rows]

    # ------------------------------------------------------------------
    # Model routing configuration and health
    # ------------------------------------------------------------------

    def upsert_model_config(
        self,
        *,
        model_name: str,
        provider: str | None = None,
        enabled: bool = True,
        priority: int = 0,
        options: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO model_configs (
                    model_name, provider, enabled, priority, options_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_name) DO UPDATE SET
                    provider = excluded.provider,
                    enabled = excluded.enabled,
                    priority = excluded.priority,
                    options_json = excluded.options_json,
                    updated_at = excluded.updated_at
                """,
                (
                    model_name,
                    provider,
                    int(enabled),
                    priority,
                    _json_dumps(options or {}),
                    now,
                    now,
                ),
            )

    def list_model_configs(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM model_configs"
        params: list[Any] = []
        if enabled_only:
            sql += " WHERE enabled = ?"
            params.append(1)
        sql += " ORDER BY priority DESC, updated_at DESC"
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._decode_model_config(row) for row in rows]

    def record_model_health(
        self,
        *,
        model_name: str,
        state: str,
        failures: int = 0,
        open_until: float | None = None,
        last_error: str | None = None,
        success: bool | None = None,
    ) -> None:
        now = utc_now()
        existing = self.get_model_health(model_name)
        last_success_at = existing.get("last_success_at") if existing else None
        last_failure_at = existing.get("last_failure_at") if existing else None
        if success is True:
            last_success_at = now
            last_error = None
        elif success is False:
            last_failure_at = now
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO model_health (
                    model_name, state, failures, open_until, last_success_at,
                    last_failure_at, last_error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_name) DO UPDATE SET
                    state = excluded.state,
                    failures = excluded.failures,
                    open_until = excluded.open_until,
                    last_success_at = excluded.last_success_at,
                    last_failure_at = excluded.last_failure_at,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (
                    model_name,
                    state,
                    failures,
                    open_until,
                    last_success_at,
                    last_failure_at,
                    last_error,
                    now,
                ),
            )

    def get_model_health(self, model_name: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM model_health WHERE model_name = ?", (model_name,)
            ).fetchone()
        return dict(row) if row else None

    def list_model_health(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM model_health ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Decoders
    # ------------------------------------------------------------------

    def _decode_job(self, row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["request"] = _json_loads(value.pop("request_json") or "{}", {})
        value["stats"] = _json_loads(value.pop("stats_json") or "{}", {})
        return value

    def _decode_node_log(self, row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["input"] = _json_loads(value.pop("input_json") or "{}", {})
        value["output"] = _json_loads(value.pop("output_json") or "{}", {})
        return value

    def _decode_kb(self, row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["allowed_user_ids"] = _json_loads(
            value.pop("allowed_user_ids_json") or "[]", []
        )
        value["metadata"] = _json_loads(value.pop("metadata_json") or "{}", {})
        return value

    def _decode_document(self, row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["metadata"] = _json_loads(value.pop("metadata_json") or "{}", {})
        return value

    def _decode_chunk(self, row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["metadata"] = _json_loads(value.pop("metadata_json") or "{}", {})
        return value

    def _decode_intent(self, row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["enabled"] = bool(value["enabled"])
        value["keywords"] = _json_loads(value.pop("keywords_json") or "[]", [])
        return value

    def _decode_mapping(self, row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["enabled"] = bool(value["enabled"])
        return value

    def _decode_trace(self, row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["success"] = None if value["success"] is None else bool(value["success"])
        value["payload"] = _json_loads(value.pop("payload_json") or "{}", {})
        return value

    def _decode_eval_case(self, row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["expected_keywords"] = _json_loads(
            value.pop("expected_keywords_json") or "[]", []
        )
        value["must_not_contain"] = _json_loads(
            value.pop("must_not_contain_json") or "[]", []
        )
        value["metadata"] = _json_loads(value.pop("metadata_json") or "{}", {})
        return value

    def _decode_model_config(self, row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["enabled"] = bool(value["enabled"])
        value["options"] = _json_loads(value.pop("options_json") or "{}", {})
        return value

    def _passes_platform_access(
        self, item: dict[str, Any], *, user_id: str, is_admin: bool
    ) -> bool:
        if is_admin:
            return True
        if item.get("visibility", "public") == "public":
            return True
        if item.get("owner_user_id") == user_id:
            return True
        allowed = item.get("allowed_user_ids") or item.get("metadata", {}).get(
            "allowed_user_ids", []
        )
        if isinstance(allowed, str):
            allowed = [part.strip() for part in allowed.split(",") if part.strip()]
        return user_id in allowed
