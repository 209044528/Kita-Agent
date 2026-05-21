from typing import Generic, TypeVar, Optional, Any
from pydantic import BaseModel

T = TypeVar('T')

class Response(BaseModel, Generic[T]):
    code: str
    info: str
    data: Optional[T] = None

    @classmethod
    def success(cls, data: Any = None, info: str = "调用成功"):
        return cls(code="0000", info=info, data=data)

    @classmethod
    def error(cls, code: str, info: str, data: Any = None):
        return cls(code=code, info=info, data=data)
