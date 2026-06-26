from typing import Optional

from pydantic import BaseModel, Field, field_validator


class KnowledgeUpsertRequestDTO(BaseModel):
    raw_text: Optional[str] = Field(None, min_length=1, description="Raw text to ingest")
    file_path: Optional[str] = Field(None, description="Deprecated server-side file path")
    tag: str = Field(..., min_length=1, description="Knowledge tag")
    source_name: str = Field(..., min_length=1, description="Knowledge source name")
    knowledge_dir: Optional[str] = Field(default=None, description="Knowledge directory")
    visibility: str = Field(default="public", description="public or private")
    allowed_user_ids: list[str] = Field(default_factory=list)

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, value: str) -> str:
        if value not in {"public", "private"}:
            raise ValueError("visibility must be public or private")
        return value

    def validate_input(self) -> None:
        if not self.raw_text and not self.file_path:
            raise ValueError("raw_text and file_path require at least one value")
        if self.raw_text and self.file_path:
            raise ValueError("raw_text and file_path cannot be provided together")
        if self.file_path:
            raise ValueError("server-side file_path is not allowed; use upload instead")


class KnowledgeSearchRequestDTO(BaseModel):
    query: str = Field(..., min_length=1, description="Search query")
    tag: Optional[str] = Field(default=None, description="Knowledge tag")
    knowledge_dir: Optional[str] = Field(default=None, description="Knowledge directory")
    initial_top_k: int = Field(default=15, ge=1, le=100)
    final_top_k: int = Field(default=5, ge=1, le=30)
    channels: list[str] = Field(default_factory=lambda: ["vector", "keyword"])
