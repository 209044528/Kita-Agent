import json
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from app.types.request.chat_request import ChatRequestDTO
from app.core.rate_limit import rate_limit_by_ip
from app.types.request.knowledge_request import KnowledgeUpsertRequestDTO
from app.types.request.knowledge_delete_request import KnowledgeDeleteRequestDTO
from app.types.response import Response
from app.application.services.chat_app_service import ChatAppService
from app.application.services.knowledge_app_service import KnowledgeAppService
from app.application.services.document_parser_service import DocumentParserService
from app.domain.agent.repository import IAgentRepository
from app.core.container import get_chat_service, get_knowledge_service, get_agent_repo
from app.core.exceptions import ResourceNotFoundError
from pydantic import BaseModel, Field
from typing import Dict, List
from loguru import logger

router = APIRouter()


def _process_knowledge_background(
    request: KnowledgeUpsertRequestDTO, 
    knowledge_service: KnowledgeAppService
):
    """后台任务：处理知识入库"""
    try:
        # 如果提供了文件路径，先解析文件
        if request.file_path:
            raw_text = DocumentParserService.parse_document_to_text(request.file_path)
        else:
            raw_text = request.raw_text

        knowledge_service.process_and_store_text(
            raw_text=raw_text,
            tag=request.tag,
            source_name=request.source_name,
        )
        logger.info(f"知识入库完成: tag={request.tag}, source={request.source_name}")
    except Exception as e:
        logger.error(f"知识入库失败: {str(e)}")


@router.post("/knowledge/upsert", response_model=Response[bool])
def upsert_knowledge(
    request: KnowledgeUpsertRequestDTO, 
    background_tasks: BackgroundTasks,
    knowledge_service: KnowledgeAppService = Depends(get_knowledge_service)
):
    """添加或更新知识"""
    # 验证输入
    request.validate_input()

    # 将入库任务提交到后台执行
    background_tasks.add_task(_process_knowledge_background, request, knowledge_service)

    return Response.success(data=True, info="入库任务已提交后台处理")


@router.delete("/knowledge/delete", response_model=Response[int])
def delete_knowledge(
    request: KnowledgeDeleteRequestDTO,
    knowledge_service: KnowledgeAppService = Depends(get_knowledge_service)
):
    """删除指定标签的知识"""
    deleted_count = knowledge_service.delete_knowledge_by_tag(request.tag)
    return Response.success(data=deleted_count)


@router.get("/sessions", response_model=Response[List[Dict]])
def get_all_sessions(agent_repo: IAgentRepository = Depends(get_agent_repo)):
    """获取所有会话列表"""
    session_ids = agent_repo.list_sessions()
    sessions = []
    for session_id in session_ids:
        agent = agent_repo.get(session_id)
        if agent:
            sessions.append({
                "id": agent.session_id,
                "title": agent.title or "未归档对话"
            })
    return Response.success(data=sessions)

@router.post("/session/rename", response_model=Response[bool])
def rename_session(
    request: Dict[str, str],
    agent_repo: IAgentRepository = Depends(get_agent_repo)
):
    """会话重命名"""
    agent = agent_repo.get(request['session_id'])
    if agent:
        agent.title = request['title']
        agent_repo.save(agent)
        return Response.success(data=True)
    raise ResourceNotFoundError(info="未找到会话")

@router.delete("/session/{session_id}", response_model=Response[bool])
def delete_session(
    session_id: str,
    agent_repo: IAgentRepository = Depends(get_agent_repo)
):
    """删除会话"""
    agent_repo.delete(session_id)
    return Response.success(data=True)

@router.get("/session/{session_id}", response_model=Response[Dict])
def get_session_history(
    session_id: str,
    agent_repo: IAgentRepository = Depends(get_agent_repo)
):
    """获取指定会话的历史消息"""
    agent = agent_repo.get(session_id)
    if not agent:
        raise ResourceNotFoundError(info="会话不存在")

    # 返回会话的消息历史
    return Response.success(data={
        "session_id": agent.session_id,
        "messages": agent.messages
    })


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequestDTO,
    _: None = Depends(rate_limit_by_ip),
    chat_app_service: ChatAppService = Depends(get_chat_service)
):
    """智能体流式对话接口 (SSE)"""
    async def event_generator():
        try:
            async for chunk in chat_app_service.do_stream_chat(
                session_id=request.session_id,
                user_input=request.user_input,
                model_name=request.model_name,
                system_prompt=request.system_prompt,
            ):
                # 遵循 SSE 格式: data: {"content": "..."}\n\n
                yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"流式对话异常: {str(e)}")
            yield f"data: {json.dumps({'content': f'系统错误: {str(e)}'}, ensure_ascii=False)}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

class PromptRequestDTO(BaseModel):
    session_id: str = Field(..., description="用户会话ID")
    system_prompt: str = Field(..., description="自定义系统提示词")


@router.post("/prompt", response_model=Response[bool])
def save_system_prompt(
    request: PromptRequestDTO,
    agent_repo: IAgentRepository = Depends(get_agent_repo)
):
    """保存用户自定义提示词"""
    agent_repo.save_prompt(request.session_id, request.system_prompt)
    return Response.success(data=True)

@router.get("/prompt", response_model=Response[str])
def get_system_prompt(
    session_id: str,
    agent_repo: IAgentRepository = Depends(get_agent_repo)
):
    """获取用户自定义提示词"""
    prompt = agent_repo.get_prompt(session_id)
    # 如果 Redis 中没有，返回空字符串让前端处理默认值
    return Response.success(data=prompt or "")
