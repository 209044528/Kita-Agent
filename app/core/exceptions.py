from typing import Any, Optional

class KitaBaseException(Exception):
    """Kita-Agent 基础异常类"""
    def __init__(self, code: str, info: str, data: Optional[Any] = None):
        self.code = code
        self.info = info
        self.data = data
        super().__init__(info)

class KnowledgeError(KitaBaseException):
    """知识库相关异常"""
    def __init__(self, info: str, data: Optional[Any] = None):
        super().__init__(code="K001", info=info, data=data)

class AgentExecutionError(KitaBaseException):
    """智能体执行异常"""
    def __init__(self, info: str, data: Optional[Any] = None):
        super().__init__(code="A001", info=info, data=data)

class ValidationError(KitaBaseException):
    """参数校验异常"""
    def __init__(self, info: str, data: Optional[Any] = None):
        super().__init__(code="V001", info=info, data=data)

class ResourceNotFoundError(KitaBaseException):
    """资源不存在异常"""
    def __init__(self, info: str, data: Optional[Any] = None):
        super().__init__(code="R404", info=info, data=data)
