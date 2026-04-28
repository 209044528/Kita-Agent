from pydantic import BaseModel, Field

class ChatRequestDTO(BaseModel):
    session_id: str = Field(..., description="用户会话ID，用于隔离记忆")
    user_input: str = Field(..., description="用户的提问内容")