from pydantic import BaseModel, Field


class KnowledgeDeleteRequestDTO(BaseModel):
    tag: str = Field(..., description="要删除的知识标签")
