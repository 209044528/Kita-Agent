from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.application.services.intent_service import IntentTreeService
from app.core.container import get_intent_service, get_knowledge_service, get_platform_store
from app.core.exceptions import ResourceNotFoundError
from app.core.security import RequestIdentity, get_identity, require_admin
from app.evaluation.rag import RAGEvaluationCase, evaluate_rag
from app.infrastructure.platform_store import PlatformStore
from app.types.response import Response


router = APIRouter()


class IntentNodeRequest(BaseModel):
    node_id: str | None = None
    parent_id: str | None = None
    name: str = Field(..., min_length=1)
    description: str | None = None
    kind: str = Field(default="KB", description="KB, MCP, or SYSTEM")
    enabled: bool = True
    priority: int = 0
    keywords: list[str] = Field(default_factory=list)
    knowledge_tag: str | None = None
    knowledge_dir: str | None = None
    mcp_server: str | None = None
    mcp_tool: str | None = None
    prompt_template: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=30)


class IntentClassifyRequest(BaseModel):
    query: str = Field(..., min_length=1)


class QueryTermMappingRequest(BaseModel):
    mapping_id: str | None = None
    source_term: str = Field(..., min_length=1)
    target_term: str = Field(..., min_length=1)
    enabled: bool = True


class KnowledgeBaseRequest(BaseModel):
    tag: str = Field(..., min_length=1)
    name: str | None = None
    knowledge_dir: str | None = None
    visibility: str = Field(default="public", pattern="^(public|private)$")
    allowed_user_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceFeedbackRequest(BaseModel):
    trace_id: str | None = None
    session_id: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    category: str | None = None
    comment: str | None = None


class EvalDatasetRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: str | None = None


class EvalCaseRequest(BaseModel):
    query: str = Field(..., min_length=1)
    expected_keywords: list[str] = Field(..., min_length=1)
    tag: str | None = None
    must_not_contain: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelConfigRequest(BaseModel):
    model_name: str = Field(..., min_length=1)
    provider: str | None = None
    enabled: bool = True
    priority: int = 0
    options: dict[str, Any] = Field(default_factory=dict)


@router.post("/platform/intents", response_model=Response[dict[str, str]])
def upsert_intent_node(
    request: IntentNodeRequest,
    service: IntentTreeService = Depends(get_intent_service),
    identity: RequestIdentity = Depends(require_admin),
):
    node_id = service.upsert_node(request.model_dump(), identity)
    return Response.success(data={"node_id": node_id})


@router.get("/platform/intents", response_model=Response[list[dict[str, Any]]])
def list_intent_nodes(
    include_disabled: bool = False,
    service: IntentTreeService = Depends(get_intent_service),
    _: RequestIdentity = Depends(require_admin),
):
    return Response.success(data=service.list_nodes(include_disabled=include_disabled))


@router.delete("/platform/intents/{node_id}", response_model=Response[bool])
def delete_intent_node(
    node_id: str,
    service: IntentTreeService = Depends(get_intent_service),
    _: RequestIdentity = Depends(require_admin),
):
    return Response.success(data=service.delete_node(node_id))


@router.post("/platform/intents/classify", response_model=Response[dict[str, Any]])
def classify_intent(
    request: IntentClassifyRequest,
    service: IntentTreeService = Depends(get_intent_service),
    identity: RequestIdentity = Depends(get_identity),
):
    route = service.route(request.query, identity)
    return Response.success(data=route.to_dict())


@router.post("/platform/query-mappings", response_model=Response[dict[str, str]])
def upsert_query_mapping(
    request: QueryTermMappingRequest,
    service: IntentTreeService = Depends(get_intent_service),
    identity: RequestIdentity = Depends(require_admin),
):
    mapping_id = service.upsert_query_mapping(
        source_term=request.source_term,
        target_term=request.target_term,
        identity=identity,
        mapping_id=request.mapping_id,
        enabled=request.enabled,
    )
    return Response.success(data={"mapping_id": mapping_id})


@router.get("/platform/query-mappings", response_model=Response[list[dict[str, Any]]])
def list_query_mappings(
    include_disabled: bool = False,
    service: IntentTreeService = Depends(get_intent_service),
    _: RequestIdentity = Depends(require_admin),
):
    return Response.success(data=service.list_query_mappings(include_disabled=include_disabled))


@router.post("/platform/knowledge/bases", response_model=Response[dict[str, str]])
def upsert_knowledge_base(
    request: KnowledgeBaseRequest,
    store: PlatformStore = Depends(get_platform_store),
    identity: RequestIdentity = Depends(require_admin),
):
    kb_id = store.upsert_knowledge_base(
        tag=request.tag,
        name=request.name,
        knowledge_dir=request.knowledge_dir,
        visibility=request.visibility,
        owner_user_id=identity.user_id,
        allowed_user_ids=request.allowed_user_ids,
        metadata=request.metadata,
    )
    return Response.success(data={"kb_id": kb_id})


@router.get("/platform/knowledge/bases", response_model=Response[list[dict[str, Any]]])
def list_knowledge_bases(
    limit: int = Query(default=100, ge=1, le=1000),
    store: PlatformStore = Depends(get_platform_store),
    identity: RequestIdentity = Depends(get_identity),
):
    return Response.success(
        data=store.list_knowledge_bases(
            user_id=identity.user_id,
            is_admin=identity.is_admin,
            limit=limit,
        )
    )


@router.get("/platform/knowledge/documents", response_model=Response[list[dict[str, Any]]])
def list_knowledge_documents(
    kb_id: str | None = None,
    tag: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    store: PlatformStore = Depends(get_platform_store),
    identity: RequestIdentity = Depends(get_identity),
):
    return Response.success(
        data=store.list_knowledge_documents(
            kb_id=kb_id,
            tag=tag,
            user_id=identity.user_id,
            is_admin=identity.is_admin,
            limit=limit,
        )
    )


@router.get("/platform/knowledge/chunks", response_model=Response[list[dict[str, Any]]])
def list_knowledge_chunks(
    document_id: str | None = None,
    kb_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    store: PlatformStore = Depends(get_platform_store),
    identity: RequestIdentity = Depends(get_identity),
):
    chunks = store.list_knowledge_chunks(document_id=document_id, kb_id=kb_id, limit=limit)
    if identity.is_admin:
        return Response.success(data=chunks)

    accessible_docs = store.list_knowledge_documents(
        kb_id=kb_id,
        user_id=identity.user_id,
        is_admin=False,
        limit=10000,
    )
    accessible_doc_ids = {doc["document_id"] for doc in accessible_docs}
    return Response.success(
        data=[chunk for chunk in chunks if chunk["document_id"] in accessible_doc_ids]
    )


@router.get("/platform/ingestion/jobs/{job_id}/nodes", response_model=Response[list[dict[str, Any]]])
def list_ingestion_node_logs(
    job_id: str,
    store: PlatformStore = Depends(get_platform_store),
    identity: RequestIdentity = Depends(get_identity),
):
    job = store.get_ingest_job(job_id)
    if not job:
        raise ResourceNotFoundError(info="摄取任务不存在")
    if job.get("user_id") != identity.user_id and not identity.is_admin:
        from app.core.exceptions import AuthorizationError

        raise AuthorizationError(info="无权查看该摄取任务")
    return Response.success(data=store.list_ingestion_node_logs(job_id))


@router.post("/platform/traces/feedback", response_model=Response[dict[str, int]])
def add_trace_feedback(
    request: TraceFeedbackRequest,
    store: PlatformStore = Depends(get_platform_store),
    identity: RequestIdentity = Depends(get_identity),
):
    feedback_id = store.insert_trace_feedback(
        trace_id=request.trace_id,
        session_id=request.session_id,
        user_id=identity.user_id,
        rating=request.rating,
        category=request.category,
        comment=request.comment,
    )
    return Response.success(data={"id": feedback_id})


@router.get("/platform/traces/feedback", response_model=Response[list[dict[str, Any]]])
def list_trace_feedback(
    trace_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    store: PlatformStore = Depends(get_platform_store),
    _: RequestIdentity = Depends(require_admin),
):
    return Response.success(data=store.read_trace_feedback(trace_id=trace_id, limit=limit))


@router.post("/platform/evaluation/datasets", response_model=Response[dict[str, str]])
def create_eval_dataset(
    request: EvalDatasetRequest,
    store: PlatformStore = Depends(get_platform_store),
    identity: RequestIdentity = Depends(require_admin),
):
    dataset_id = store.create_eval_dataset(
        name=request.name,
        description=request.description,
        created_by=identity.user_id,
    )
    return Response.success(data={"dataset_id": dataset_id})


@router.get("/platform/evaluation/datasets", response_model=Response[list[dict[str, Any]]])
def list_eval_datasets(
    limit: int = Query(default=100, ge=1, le=1000),
    store: PlatformStore = Depends(get_platform_store),
    _: RequestIdentity = Depends(require_admin),
):
    return Response.success(data=store.list_eval_datasets(limit=limit))


@router.post("/platform/evaluation/datasets/{dataset_id}/cases", response_model=Response[dict[str, str]])
def add_eval_case(
    dataset_id: str,
    request: EvalCaseRequest,
    store: PlatformStore = Depends(get_platform_store),
    _: RequestIdentity = Depends(require_admin),
):
    case_id = store.add_eval_case(
        dataset_id=dataset_id,
        query=request.query,
        expected_keywords=request.expected_keywords,
        tag=request.tag,
        must_not_contain=request.must_not_contain,
        metadata=request.metadata,
    )
    return Response.success(data={"case_id": case_id})


@router.get("/platform/evaluation/datasets/{dataset_id}/cases", response_model=Response[list[dict[str, Any]]])
def list_eval_cases(
    dataset_id: str,
    store: PlatformStore = Depends(get_platform_store),
    _: RequestIdentity = Depends(require_admin),
):
    return Response.success(data=store.list_eval_cases(dataset_id))


@router.post("/platform/evaluation/datasets/{dataset_id}/run", response_model=Response[dict[str, Any]])
def run_eval_dataset(
    dataset_id: str,
    store: PlatformStore = Depends(get_platform_store),
    knowledge_service=Depends(get_knowledge_service),
    identity: RequestIdentity = Depends(require_admin),
):
    cases = [
        RAGEvaluationCase(
            query=item["query"],
            expected_keywords=item["expected_keywords"],
            tag=item.get("tag"),
            must_not_contain=item.get("must_not_contain", []),
        )
        for item in store.list_eval_cases(dataset_id)
    ]

    def retrieve(query: str, tag: str | None = None) -> str:
        return knowledge_service.retrieve_knowledge(
            query,
            tag=tag,
            user_id=identity.user_id,
            is_admin=identity.is_admin,
        )

    return Response.success(data=evaluate_rag(cases, retrieve).model_dump())


@router.post("/platform/llm/models", response_model=Response[bool])
def upsert_model_config(
    request: ModelConfigRequest,
    store: PlatformStore = Depends(get_platform_store),
    _: RequestIdentity = Depends(require_admin),
):
    store.upsert_model_config(
        model_name=request.model_name,
        provider=request.provider,
        enabled=request.enabled,
        priority=request.priority,
        options=request.options,
    )
    return Response.success(data=True)


@router.get("/platform/llm/models", response_model=Response[list[dict[str, Any]]])
def list_model_configs(
    enabled_only: bool = False,
    store: PlatformStore = Depends(get_platform_store),
    _: RequestIdentity = Depends(require_admin),
):
    return Response.success(data=store.list_model_configs(enabled_only=enabled_only))


@router.get("/platform/llm/health", response_model=Response[list[dict[str, Any]]])
def list_model_health(
    store: PlatformStore = Depends(get_platform_store),
    _: RequestIdentity = Depends(require_admin),
):
    return Response.success(data=store.list_model_health())
