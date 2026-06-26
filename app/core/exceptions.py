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


class AuthenticationError(KitaBaseException):
    def __init__(self, info: str = "认证失败", data: Optional[Any] = None):
        super().__init__(code="AUTH401", info=info, data=data)


class AuthorizationError(KitaBaseException):
    def __init__(self, info: str = "无权执行此操作", data: Optional[Any] = None):
        super().__init__(code="AUTH403", info=info, data=data)


class SessionBusyError(KitaBaseException):
    def __init__(self, info: str = "当前会话正在处理中", data: Optional[Any] = None):
        super().__init__(code="A409", info=info, data=data)


class AgentCancelledError(KitaBaseException):
    def __init__(self, info: str = "任务已取消", data: Optional[Any] = None):
        super().__init__(code="A499", info=info, data=data)


class LLMError(KitaBaseException):
    def __init__(
        self,
        info: str,
        *,
        error_type: str = "unknown",
        retryable: bool = True,
        data: Optional[Any] = None,
    ):
        payload = {"error_type": error_type, "retryable": retryable}
        if isinstance(data, dict):
            payload.update(data)
        super().__init__(code="LLM001", info=info, data=payload)
        self.error_type = error_type
        self.retryable = retryable
