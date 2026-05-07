from pydantic import BaseModel, Field


class KnowledgeUpsertRequestDTO(BaseModel):
    raw_text: str = Field(..., min_length=1, description="待入库的原始知识文本")
    tag: str = Field(..., min_length=1, description="知识标签")
    source_name: str = Field(..., min_length=1, description="知识来源标识")