from fastapi import APIRouter
from app.types.request.chat_request import ChatRequestDTO
from app.types.request.knowledge_request import KnowledgeUpsertRequestDTO
from app.types.request.knowledge_delete_request import KnowledgeDeleteRequestDTO
from app.types.response import Response
from app.application.services.chat_app_service import ChatAppService
from app.application.services.knowledge_app_service import KnowledgeAppService
from app.infrastructure.llm.openai_client import OpenAILlmServiceImpl
from app.infrastructure.repository.pgvector_knowledge_repo import PgVectorKnowledgeRepository
from app.infrastructure.repository.redis_agent_repo import RedisAgentRepository
from pydantic import BaseModel, Field

router = APIRouter()

llm_service = OpenAILlmServiceImpl()
knowledge_repo = PgVectorKnowledgeRepository()
knowledge_service = KnowledgeAppService(knowledge_repo)
chat_app_service = ChatAppService(llm_service, knowledge_service=knowledge_service)
agent_repo = RedisAgentRepository()


@router.post("/knowledge/upsert", response_model=Response[bool])
def upsert_knowledge(request: KnowledgeUpsertRequestDTO):
    try:
        knowledge_service.process_and_store_text(
            raw_text=request.raw_text,
            tag=request.tag,
            source_name=request.source_name,
        )
        return Response.success(data=True)
    except Exception as e:
        return Response.error(code="500", info=str(e))


@router.delete("/knowledge/delete", response_model=Response[int])
def delete_knowledge(request: KnowledgeDeleteRequestDTO):
    try:
        deleted_count = knowledge_service.delete_knowledge_by_tag(request.tag)
        return Response.success(data=deleted_count)
    except Exception as e:
        return Response.error(code="500", info=str(e))


@router.get("/sessions", response_model=Response[list[str]])
def get_all_sessions():
    try:
        sessions = agent_repo.list_sessions()
        return Response.success(data=sessions)
    except Exception as e:
        return Response.error(code="500", info=str(e))


@router.get("/session/{session_id}", response_model=Response[dict])
def get_session_history(session_id: str):
    """获取指定会话的历史消息"""
    try:
        agent = agent_repo.get(session_id)
        if not agent:
            return Response.error(code="404", info="会话不存在")

        # 返回会话的消息历史
        return Response.success(data={
            "session_id": agent.session_id,
            "messages": agent.messages
        })
    except Exception as e:
        return Response.error(code="500", info=str(e))


@router.post("/chat", response_model=Response[str])
def chat(request: ChatRequestDTO):
    try:
        reply = chat_app_service.do_chat(
            session_id=request.session_id,
            user_input=request.user_input,
            knowledge_tag=request.knowledge_tag,
            system_prompt=request.system_prompt,
        )

        return Response.success(data=reply)
    except Exception as e:
        return Response.error(code="500", info=str(e))

class PromptRequestDTO(BaseModel):
    session_id: str = Field(..., description="用户会话ID")
    system_prompt: str = Field(..., description="自定义系统提示词")


@router.post("/prompt", response_model=Response[bool])
def save_system_prompt(request: PromptRequestDTO):
    """保存用户自定义提示词"""
    try:
        agent_repo.save_prompt(request.session_id, request.system_prompt)
        return Response.success(data=True)
    except Exception as e:
        return Response.error(code="500", info=str(e))

@router.get("/prompt", response_model=Response[str])
def get_system_prompt(session_id: str):
    """获取用户自定义提示词"""
    try:
        prompt = agent_repo.get_prompt(session_id)
        # 如果 Redis 中没有，返回空字符串让前端处理默认值
        return Response.success(data=prompt or "")
    except Exception as e:
        return Response.error(code="500", info=str(e))