from fastapi import APIRouter, BackgroundTasks, Depends
from app.types.response import Response
from app.core.config import settings
from app.core.exceptions import KnowledgeError
from app.core.container import get_knowledge_service
from app.application.services.knowledge_app_service import KnowledgeAppService
from loguru import logger
from pydantic import BaseModel, Field
import redis
import psycopg2
import json
from typing import List, Dict, Any

router = APIRouter()


class GitIngestRequest(BaseModel):
    repo_url: str = Field(..., description="Git 仓库链接")
    branch: str = Field(default="main", description="分支名称")
    knowledge_tag: str = Field(default=None, description="知识库标签")


def _background_git_ingest(
    request: GitIngestRequest, 
    knowledge_service: KnowledgeAppService
):
    """后台执行 Git 解析入库"""
    try:
        knowledge_service.ingest_git_repo(
            repo_url=request.repo_url,
            branch=request.branch,
            knowledge_tag=request.knowledge_tag
        )
    except Exception as e:
        logger.error(f"Git 仓库 {request.repo_url} 后台入库失败: {str(e)}")


@router.post("/knowledge/git", response_model=Response[None])
def ingest_git_knowledge(
    request: GitIngestRequest,
    background_tasks: BackgroundTasks,
    knowledge_service: KnowledgeAppService = Depends(get_knowledge_service)
):
    """一键解析 Git 仓库并入库"""
    background_tasks.add_task(_background_git_ingest, request, knowledge_service)
    return Response.success(info="Git 仓库解析任务已提交后台执行")


@router.get("/maintenance/redis", response_model=Response[List[Dict[str, Any]]])
def get_redis_sessions():
    """查看 Redis 中的会话数据"""
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    keys = client.keys("kita:*")

    sessions = []
    for key in keys:
        session_id = key.split(":")[-1]
        ttl = client.ttl(key)
        data = client.get(key)

        if data and data.strip():
            try:
                agent_data = json.loads(data)
            except json.JSONDecodeError:
                continue
            message_count = len(agent_data.get("messages", []))
            messages = agent_data.get("messages", [])

            recent_messages = []
            for msg in messages[-4:]:
                content = msg.get("content", "")
                preview = content[:100] + "..." if len(content) > 100 else content
                recent_messages.append({
                    "role": msg.get("role", "unknown"),
                    "content": preview
                })

            sessions.append({
                "session_id": session_id,
                "ttl": ttl,
                "message_count": message_count,
                "recent_messages": recent_messages
            })

    return Response.success(data=sessions)


@router.get("/maintenance/knowledge", response_model=Response[Dict[str, Any]])
def get_knowledge_stats():
    """查看 PostgreSQL 知识库统计"""
    try:
        conn = psycopg2.connect(
            host=settings.PG_VECTOR_HOST,
            port=settings.PG_VECTOR_PORT,
            user=settings.PG_VECTOR_USER,
            password=settings.PG_VECTOR_PASSWORD,
            database=settings.PG_VECTOR_DB
        )
        cursor = conn.cursor()

        cursor.execute("SELECT name, uuid FROM langchain_pg_collection;")
        collections = cursor.fetchall()

        cursor.execute("""
            SELECT
                c.name as collection_name,
                COUNT(e.id) as doc_count,
                COUNT(DISTINCT e.cmetadata->>'knowledge_tag') as tag_count
            FROM langchain_pg_collection c
            LEFT JOIN langchain_pg_embedding e ON c.uuid = e.collection_id
            GROUP BY c.name;
        """)
        stats = cursor.fetchall()

        cursor.execute("SELECT COUNT(*) FROM langchain_pg_embedding;")
        total_docs = cursor.fetchone()[0]

        documents = []
        if total_docs > 0:
            cursor.execute("""
                SELECT
                    e.document,
                    e.cmetadata->>'knowledge_tag' as tag,
                    e.cmetadata->>'source' as source,
                    LENGTH(e.document) as doc_length
                FROM langchain_pg_embedding e
                ORDER BY e.id
                LIMIT 50;
            """)
            docs = cursor.fetchall()

            for doc, tag, source, length in docs:
                preview = doc[:100] + "..." if len(doc) > 100 else doc
                documents.append({
                    "content": preview,
                    "tag": tag or "N/A",
                    "source": source or "N/A",
                    "length": length
                })

            cursor.execute("""
                SELECT
                    e.cmetadata->>'knowledge_tag' as tag,
                    COUNT(*) as count
                FROM langchain_pg_embedding e
                GROUP BY e.cmetadata->>'knowledge_tag'
                ORDER BY count DESC;
            """)
            tag_stats = cursor.fetchall()
        else:
            tag_stats = []

        cursor.close()
        conn.close()

        return Response.success(data={
            "collections": [{"name": c[0], "uuid": c[1]} for c in collections],
            "stats": [{"collection": s[0], "doc_count": s[1], "tag_count": s[2]} for s in stats],
            "total_docs": total_docs,
            "documents": documents,
            "tag_stats": [{"tag": t[0], "count": t[1]} for t in tag_stats]
        })
    except Exception as e:
        logger.error(f"查询统计失败: {str(e)}")
        raise KnowledgeError(info=f"查询统计失败: {str(e)}")
