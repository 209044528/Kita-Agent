from pydantic import BaseModel, Field

class ChatRequestDTO(BaseModel):
    session_id: str = Field(..., description="用户会话ID，用于隔离记忆")
    user_input: str = Field(..., description="用户的提问内容")
    knowledge_tag: str | None = Field(default=None, description="可选知识标签，仅检索该标签知识")
    system_prompt: str | None = Field(default=None, description="自定义系统提示词")