import asyncio
import json
import os
import tempfile
from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from fastapi.responses import StreamingResponse
from app.types.request.chat_request import ChatRequestDTO
from app.core.rate_limit import rate_limit_by_ip
from app.types.request.knowledge_request import KnowledgeSearchRequestDTO, KnowledgeUpsertRequestDTO
from app.types.request.knowledge_delete_request import KnowledgeDeleteRequestDTO
from app.types.response import Response
from app.application.services.chat_app_service import ChatAppService
from app.application.services.knowledge_app_service import KnowledgeAppService
from app.application.services.document_parser_service import DocumentParserService
from app.domain.agent.repository import IAgentRepository
from app.core.container import (
    get_chat_service,
    get_knowledge_service,
    get_agent_repo,
    get_task_manager,
)
from app.core.config import settings
from app.core.exceptions import (
    AgentCancelledError,
    KitaBaseException,
    ResourceNotFoundError,
)
from app.core.input_security import validate_upload_content, validate_upload_name
from app.core.security import RequestIdentity, get_identity, require_admin
from app.core.task_manager import AgentTaskManager
from pydantic import BaseModel, Field
from typing import Dict, List
from loguru import logger

router = APIRouter()


def _process_knowledge_background(
    request: KnowledgeUpsertRequestDTO, 
    knowledge_service: KnowledgeAppService,
    identity: RequestIdentity,
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
            user_id=identity.user_id,
            visibility=request.visibility,
            allowed_user_ids=request.allowed_user_ids,
            knowledge_dir=request.knowledge_dir,
        )
        logger.info(f"知识入库完成: tag={request.tag}, source={request.source_name}")
    except Exception as e:
        logger.error(f"知识入库失败: {str(e)}")


def _process_uploaded_knowledge_background(
    content: bytes,
    filename: str,
    tag: str,
    source_name: str,
    knowledge_service: KnowledgeAppService,
    identity: RequestIdentity,
    visibility: str = "public",
    knowledge_dir: str | None = None,
):
    suffix = os.path.splitext(filename)[1]
    path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as file:
            file.write(content)
            path = file.name
        raw_text = DocumentParserService.parse_document_to_text(path)
        knowledge_service.process_and_store_text(
            raw_text=raw_text,
            tag=tag,
            source_name=source_name or filename,
            user_id=identity.user_id,
            visibility=visibility,
            knowledge_dir=knowledge_dir,
        )
    except Exception as exc:
        logger.error("上传文件入库失败: {}", exc)
    finally:
        if path and os.path.exists(path):
            os.unlink(path)


@router.post("/knowledge/upsert", response_model=Response[bool])
def upsert_knowledge(
    request: KnowledgeUpsertRequestDTO, 
    background_tasks: BackgroundTasks,
    knowledge_service: KnowledgeAppService = Depends(get_knowledge_service),
    identity: RequestIdentity = Depends(require_admin),
):
    """添加或更新知识"""
    # 验证输入
    request.validate_input()

    # 将入库任务提交到后台执行
    background_tasks.add_task(_process_knowledge_background, request, knowledge_service, identity)

    return Response.success(data=True, info="入库任务已提交后台处理")


@router.post("/knowledge/upload", response_model=Response[bool])
async def upload_knowledge(
    background_tasks: BackgroundTasks,
    tag: str,
    source_name: str = "",
    visibility: str = "public",
    knowledge_dir: str | None = None,
    file: UploadFile = File(...),
    knowledge_service: KnowledgeAppService = Depends(get_knowledge_service),
    identity: RequestIdentity = Depends(require_admin),
):
    filename = validate_upload_name(file.filename)
    content = await file.read(settings.MAX_UPLOAD_BYTES + 1)
    await file.close()
    if len(content) > settings.MAX_UPLOAD_BYTES:
        from app.core.exceptions import ValidationError

        raise ValidationError(
            f"文件超过 {settings.MAX_UPLOAD_BYTES} 字节限制"
        )
    validate_upload_content(filename, content)
    background_tasks.add_task(
        _process_uploaded_knowledge_background,
        content,
        filename,
        tag,
        source_name,
        knowledge_service,
        identity,
        visibility,
        knowledge_dir,
    )
    return Response.success(data=True, info="文件入库任务已提交")


@router.post("/knowledge/search", response_model=Response[List[Dict]])
def search_knowledge(
    request: KnowledgeSearchRequestDTO,
    knowledge_service: KnowledgeAppService = Depends(get_knowledge_service),
    identity: RequestIdentity = Depends(get_identity),
):
    chunks = knowledge_service.retrieve_chunks(
        user_query=request.query,
        tag=request.tag,
        initial_top_k=request.initial_top_k,
        final_top_k=request.final_top_k,
        user_id=identity.user_id,
        is_admin=identity.is_admin,
        knowledge_dir=request.knowledge_dir,
        channels=request.channels,
    )
    return Response.success(data=[chunk.model_dump() for chunk in chunks])


@router.delete("/knowledge/delete", response_model=Response[int])
def delete_knowledge(
    request: KnowledgeDeleteRequestDTO,
    knowledge_service: KnowledgeAppService = Depends(get_knowledge_service),
    _: RequestIdentity = Depends(require_admin),
):
    """删除指定标签的知识"""
    deleted_count = knowledge_service.delete_knowledge_by_tag(request.tag)
    return Response.success(data=deleted_count)


@router.get("/sessions", response_model=Response[List[Dict]])
def get_all_sessions(
    agent_repo: IAgentRepository = Depends(get_agent_repo),
    identity: RequestIdentity = Depends(get_identity),
):
    """获取所有会话列表"""
    session_ids = agent_repo.list_sessions(identity.user_id)
    sessions = []
    for session_id in session_ids:
        agent = agent_repo.get(session_id, identity.user_id)
        if agent:
            sessions.append({
                "id": agent.session_id,
                "title": agent.title or "未归档对话"
            })
    return Response.success(data=sessions)

@router.post("/session/rename", response_model=Response[bool])
def rename_session(
    request: Dict[str, str],
    agent_repo: IAgentRepository = Depends(get_agent_repo),
    identity: RequestIdentity = Depends(get_identity),
):
    """会话重命名"""
    agent = agent_repo.get(request['session_id'], identity.user_id)
    if agent:
        agent.title = request['title']
        agent_repo.save(agent, identity.user_id)
        return Response.success(data=True)
    raise ResourceNotFoundError(info="未找到会话")

@router.delete("/session/{session_id}", response_model=Response[bool])
def delete_session(
    session_id: str,
    agent_repo: IAgentRepository = Depends(get_agent_repo),
    identity: RequestIdentity = Depends(get_identity),
):
    """删除会话"""
    agent_repo.delete(session_id, identity.user_id)
    return Response.success(data=True)

@router.get("/session/{session_id}", response_model=Response[Dict])
def get_session_history(
    session_id: str,
    agent_repo: IAgentRepository = Depends(get_agent_repo),
    identity: RequestIdentity = Depends(get_identity),
):
    """获取指定会话的历史消息"""
    agent = agent_repo.get(session_id, identity.user_id)
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
    chat_app_service: ChatAppService = Depends(get_chat_service),
    task_manager: AgentTaskManager = Depends(get_task_manager),
    identity: RequestIdentity = Depends(get_identity),
):
    """智能体流式对话接口 (SSE)"""
    task_id = task_manager.new_task_id()

    def sse(event: str, data: dict | str) -> str:
        payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        return f"event: {event}\ndata: {payload}\n\n"

    async def event_generator():
        try:
            yield sse(
                "meta",
                {
                    "task_id": task_id,
                    "session_id": request.session_id,
                },
            )
            async with task_manager.run(
                task_id, identity, request.session_id
            ):
                async for event in chat_app_service.do_stream_chat(
                    session_id=request.session_id,
                    user_input=request.user_input,
                    model_name=request.model_name,
                    system_prompt=request.system_prompt,
                    identity=identity,
                    task_id=task_id,
                    knowledge_tag=request.knowledge_tag,
                    knowledge_dir=request.knowledge_dir,
                ):
                    yield sse(event.event, event.payload())
        except (AgentCancelledError, asyncio.CancelledError):
            yield sse("cancel", {"task_id": task_id, "message": "任务已取消"})
        except KitaBaseException as exc:
            yield sse(
                "error",
                {"code": exc.code, "message": exc.info, "data": exc.data},
            )
        except Exception as e:
            logger.exception("流式对话异常")
            yield sse("error", {"code": "9999", "message": str(e)})
        finally:
            yield sse("done", "[DONE]")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"X-Task-ID": task_id},
    )


@router.post("/chat/tasks/{task_id}/cancel", response_model=Response[bool])
async def cancel_chat_task(
    task_id: str,
    task_manager: AgentTaskManager = Depends(get_task_manager),
    identity: RequestIdentity = Depends(get_identity),
):
    cancelled = await task_manager.cancel(task_id, identity)
    return Response.success(data=cancelled)

class PromptRequestDTO(BaseModel):
    session_id: str = Field(..., description="用户会话ID")
    system_prompt: str = Field(..., description="自定义系统提示词")


@router.post("/prompt", response_model=Response[bool])
def save_system_prompt(
    request: PromptRequestDTO,
    agent_repo: IAgentRepository = Depends(get_agent_repo),
    identity: RequestIdentity = Depends(get_identity),
):
    """保存用户自定义提示词"""
    agent_repo.save_prompt(request.session_id, request.system_prompt, identity.user_id)
    return Response.success(data=True)

@router.get("/prompt", response_model=Response[str])
def get_system_prompt(
    session_id: str,
    agent_repo: IAgentRepository = Depends(get_agent_repo),
    identity: RequestIdentity = Depends(get_identity),
):
    """获取用户自定义提示词"""
    prompt = agent_repo.get_prompt(session_id, identity.user_id)
    # 如果 Redis 中没有，返回空字符串让前端处理默认值
    return Response.success(data=prompt or "")
