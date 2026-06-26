from typing import Any

from fastapi import APIRouter, Depends, Query

from app.core.container import get_knowledge_service, get_observability
from app.evaluation.rag import RAGEvaluationCase, evaluate_rag
from app.infrastructure.observability import ObservabilityService
from app.types.response import Response
from app.core.security import RequestIdentity, require_admin


router = APIRouter()


@router.get("/observability/metrics", response_model=Response[dict[str, Any]])
def get_metrics(
    observability: ObservabilityService = Depends(get_observability),
    _: RequestIdentity = Depends(require_admin),
):
    return Response.success(data=observability.metrics())


@router.get("/observability/traces", response_model=Response[list[dict[str, Any]]])
def get_traces(
    session_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    observability: ObservabilityService = Depends(get_observability),
    _: RequestIdentity = Depends(require_admin),
):
    return Response.success(data=observability.read_traces(session_id, limit))


@router.post("/evaluation/rag", response_model=Response[dict[str, Any]])
def run_rag_evaluation(
    cases: list[RAGEvaluationCase],
    knowledge_service=Depends(get_knowledge_service),
    _: RequestIdentity = Depends(require_admin),
):
    report = evaluate_rag(cases, knowledge_service.retrieve_knowledge)
    return Response.success(data=report.model_dump())
