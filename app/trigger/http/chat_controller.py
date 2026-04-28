from fastapi import APIRouter
from app.types.request.chat_request import ChatRequestDTO
from app.types.response import Response
from app.application.services.chat_app_service import ChatAppService
from app.infrastructure.llm.openai_client import OpenAILlmServiceImpl

router = APIRouter()

llm_service = OpenAILlmServiceImpl()
chat_app_service = ChatAppService(llm_service)


@router.post("/chat", response_model=Response[str])
def chat(request: ChatRequestDTO):
    try:
        reply = chat_app_service.do_chat(request.session_id, request.user_input)

        return Response.success(data=reply)
    except Exception as e:
        return Response.error(code="500", info=str(e))