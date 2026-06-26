import json
from typing import Any, Dict, List

import psycopg2
import redis
from fastapi import APIRouter, BackgroundTasks, Depends
from loguru import logger
from pydantic import BaseModel, Field

from app.application.services.knowledge_app_service import KnowledgeAppService
from app.core.config import settings
from app.core.container import get_knowledge_service
from app.core.exceptions import KnowledgeError
from app.core.input_security import validate_git_url
from app.core.security import RequestIdentity, require_admin
from app.types.response import Response

router = APIRouter()


class GitIngestRequest(BaseModel):
    repo_url: str = Field(..., description="Git repository URL")
    branch: str = Field(default="main", description="Branch name")
    knowledge_tag: str | None = Field(default=None, description="Knowledge tag")
    knowledge_dir: str | None = Field(default=None, description="Knowledge directory")
    visibility: str = Field(default="public", description="public or private")
    allowed_user_ids: list[str] = Field(default_factory=list)


def _background_git_ingest(
    request: GitIngestRequest,
    knowledge_service: KnowledgeAppService,
    identity: RequestIdentity,
):
    try:
        knowledge_service.ingest_git_repo(
            repo_url=request.repo_url,
            branch=request.branch,
            knowledge_tag=request.knowledge_tag,
            user_id=identity.user_id,
            visibility=request.visibility,
            allowed_user_ids=request.allowed_user_ids,
            knowledge_dir=request.knowledge_dir,
        )
    except Exception as e:
        logger.error("Git repository {} ingest failed: {}", request.repo_url, e)


@router.post("/knowledge/git", response_model=Response[None])
def ingest_git_knowledge(
    request: GitIngestRequest,
    background_tasks: BackgroundTasks,
    knowledge_service: KnowledgeAppService = Depends(get_knowledge_service),
    identity: RequestIdentity = Depends(require_admin),
):
    request.repo_url = validate_git_url(request.repo_url)
    background_tasks.add_task(_background_git_ingest, request, knowledge_service, identity)
    return Response.success(info="Git repository ingest task submitted")


@router.get("/maintenance/redis", response_model=Response[List[Dict[str, Any]]])
def get_redis_sessions(_: RequestIdentity = Depends(require_admin)):
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    sessions = []
    for key in client.scan_iter("kita:agent:session:*"):
        parts = key.split(":")
        session_id = parts[-1]
        user_id = parts[-2] if len(parts) >= 5 else "anonymous"
        ttl = client.ttl(key)
        data = client.get(key)

        if not data or not data.strip():
            continue
        try:
            agent_data = json.loads(data)
        except json.JSONDecodeError:
            continue

        messages = agent_data.get("messages", [])
        recent_messages = []
        for msg in messages[-4:]:
            content = msg.get("content", "")
            recent_messages.append(
                {
                    "role": msg.get("role", "unknown"),
                    "content": content[:100] + "..." if len(content) > 100 else content,
                }
            )

        sessions.append(
            {
                "user_id": user_id,
                "session_id": session_id,
                "ttl": ttl,
                "message_count": len(messages),
                "recent_messages": recent_messages,
            }
        )

    return Response.success(data=sessions)


@router.get("/maintenance/knowledge", response_model=Response[Dict[str, Any]])
def get_knowledge_stats(_: RequestIdentity = Depends(require_admin)):
    try:
        conn = psycopg2.connect(
            host=settings.PG_VECTOR_HOST,
            port=settings.PG_VECTOR_PORT,
            user=settings.PG_VECTOR_USER,
            password=settings.PG_VECTOR_PASSWORD,
            database=settings.PG_VECTOR_DB,
        )
        cursor = conn.cursor()

        cursor.execute("SELECT name, uuid FROM langchain_pg_collection;")
        collections = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                c.name as collection_name,
                COUNT(e.id) as doc_count,
                COUNT(DISTINCT e.cmetadata->>'knowledge_tag') as tag_count
            FROM langchain_pg_collection c
            LEFT JOIN langchain_pg_embedding e ON c.uuid = e.collection_id
            GROUP BY c.name;
            """
        )
        stats = cursor.fetchall()

        cursor.execute("SELECT COUNT(*) FROM langchain_pg_embedding;")
        total_docs = cursor.fetchone()[0]

        documents = []
        tag_stats = []
        dir_stats = []
        if total_docs > 0:
            cursor.execute(
                """
                SELECT
                    e.document,
                    e.cmetadata->>'knowledge_tag' as tag,
                    e.cmetadata->>'source' as source,
                    e.cmetadata->>'knowledge_dir' as knowledge_dir,
                    e.cmetadata->>'visibility' as visibility,
                    LENGTH(e.document) as doc_length
                FROM langchain_pg_embedding e
                ORDER BY e.id
                LIMIT 50;
                """
            )
            for doc, tag, source, knowledge_dir, visibility, length in cursor.fetchall():
                documents.append(
                    {
                        "content": doc[:100] + "..." if len(doc) > 100 else doc,
                        "tag": tag or "N/A",
                        "source": source or "N/A",
                        "knowledge_dir": knowledge_dir or "/",
                        "visibility": visibility or "public",
                        "length": length,
                    }
                )

            cursor.execute(
                """
                SELECT e.cmetadata->>'knowledge_tag' as tag, COUNT(*) as count
                FROM langchain_pg_embedding e
                GROUP BY e.cmetadata->>'knowledge_tag'
                ORDER BY count DESC;
                """
            )
            tag_stats = cursor.fetchall()

            cursor.execute(
                """
                SELECT COALESCE(NULLIF(e.cmetadata->>'knowledge_dir', ''), '/') as dir, COUNT(*) as count
                FROM langchain_pg_embedding e
                GROUP BY dir
                ORDER BY count DESC;
                """
            )
            dir_stats = cursor.fetchall()

        cursor.close()
        conn.close()

        return Response.success(
            data={
                "collections": [{"name": c[0], "uuid": c[1]} for c in collections],
                "stats": [
                    {"collection": s[0], "doc_count": s[1], "tag_count": s[2]}
                    for s in stats
                ],
                "total_docs": total_docs,
                "documents": documents,
                "tag_stats": [{"tag": t[0], "count": t[1]} for t in tag_stats],
                "dir_stats": [{"dir": d[0], "count": d[1]} for d in dir_stats],
            }
        )
    except Exception as e:
        logger.error("Knowledge stats query failed: {}", e)
        raise KnowledgeError(info=f"查询统计失败: {str(e)}")
