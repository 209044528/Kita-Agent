from pydantic import BaseModel, Field


class ChatRequestDTO(BaseModel):
    session_id: str = Field(..., description="User session id")
    user_input: str = Field(..., description="User input")
    model_name: str | None = Field(default=None, description="Optional chat model")
    knowledge_tag: str | None = Field(default=None, description="Optional knowledge tag")
    knowledge_dir: str | None = Field(default=None, description="Optional knowledge directory")
    system_prompt: str | None = Field(default=None, description="Optional system prompt")
