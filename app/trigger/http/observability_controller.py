from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.container import get_knowledge_service, get_observability, get_mcp_client
from app.evaluation.rag import RAGEvaluationCase, evaluate_rag
from app.infrastructure.observability import ObservabilityService
from app.infrastructure.mcp.client import MCPClientService
from app.types.response import Response
from app.core.security import RequestIdentity, require_admin


router = APIRouter()


class MCPToolCallRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


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
    return Response.success(data=observability.read_trace_events(session_id=session_id, limit=limit))


@router.get("/observability/bad-cases", response_model=Response[list[dict[str, Any]]])
def get_bad_cases(
    limit: int = Query(default=100, ge=1, le=1000),
    observability: ObservabilityService = Depends(get_observability),
    _: RequestIdentity = Depends(require_admin),
):
    return Response.success(data=observability.read_bad_cases(limit=limit))


@router.get("/observability/trace-summary", response_model=Response[dict[str, Any]])
def get_trace_summary(
    observability: ObservabilityService = Depends(get_observability),
    _: RequestIdentity = Depends(require_admin),
):
    return Response.success(data=observability.trace_summary())


@router.get("/mcp/client/servers", response_model=Response[list[dict[str, str]]])
def list_mcp_servers(
    client: MCPClientService = Depends(get_mcp_client),
    _: RequestIdentity = Depends(require_admin),
):
    return Response.success(data=client.list_servers())


@router.get("/mcp/client/{server_name}/tools", response_model=Response[list[dict[str, Any]]])
async def list_mcp_tools(
    server_name: str,
    client: MCPClientService = Depends(get_mcp_client),
    _: RequestIdentity = Depends(require_admin),
):
    return Response.success(data=await client.list_tools(server_name))


@router.post("/mcp/client/{server_name}/tools/{tool_name}", response_model=Response[dict[str, Any]])
async def call_mcp_tool(
    server_name: str,
    tool_name: str,
    request: MCPToolCallRequest,
    client: MCPClientService = Depends(get_mcp_client),
    _: RequestIdentity = Depends(require_admin),
):
    return Response.success(data=await client.call_tool(server_name, tool_name, request.arguments))


@router.post("/evaluation/rag", response_model=Response[dict[str, Any]])
def run_rag_evaluation(
    cases: list[RAGEvaluationCase],
    knowledge_service=Depends(get_knowledge_service),
    _: RequestIdentity = Depends(require_admin),
):
    report = evaluate_rag(cases, knowledge_service.retrieve_knowledge)
    return Response.success(data=report.model_dump())
