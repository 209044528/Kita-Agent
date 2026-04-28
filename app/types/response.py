from typing import Generic, TypeVar, Optional
from pydantic import BaseModel

T = TypeVar('T')

class Response(BaseModel, Generic[T]):
    code: str
    info: str
    data: Optional[T] = None

    @classmethod
    def success(cls, data: T):
        return cls(code="0000", info="调用成功", data=data)

    @classmethod
    def error(cls, code: str, info: str):
        return cls(code=code, info=info, data=None)