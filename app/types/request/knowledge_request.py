from pydantic import BaseModel, Field
from typing import Optional


class KnowledgeUpsertRequestDTO(BaseModel):
    raw_text: Optional[str] = Field(None, min_length=1, description="待入库的原始知识文本")
    file_path: Optional[str] = Field(None, description="本地文件路径（用于文件上传场景）")
    tag: str = Field(..., min_length=1, description="知识标签")
    source_name: str = Field(..., min_length=1, description="知识来源标识")

    def validate_input(self) -> None:
        if not self.raw_text and not self.file_path:
            raise ValueError("raw_text 和 file_path 至少需要提供一个")
        if self.raw_text and self.file_path:
            raise ValueError("raw_text 和 file_path 不能同时提供")