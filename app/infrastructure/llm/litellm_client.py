import os
import asyncio
import litellm
from loguru import logger
from typing import AsyncGenerator
from app.core.config import settings
from app.domain.agent.repository import ILLMClient
from app.infrastructure.llm.zhipuai_client import ZhipuAIClient
from app.core.exceptions import LLMError

# 禁用 LiteLLM 遥测和远程价格表拉取（必须在所有业务 import 之前设置）
litellm.telemetry = False
litellm.suppress_debug_info = True

class LiteLLMClient(ILLMClient):
    def __init__(self):
        # 配置 LiteLLM 环境变量
        os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
        os.environ["OPENAI_API_BASE"] = settings.OPENAI_BASE_URL

        self.default_model = settings.MODEL_NAME
        self.zhipu_client = ZhipuAIClient()
        
        # 允许 LiteLLM 在模型未找到时抛出异常
        litellm.drop_params = True

    async def stream_chat(self, messages: list, model: str = None, **kwargs) -> AsyncGenerator[str, None]:
        target_model = model or self.default_model

        # 如果是 GLM 模型，且没有显式指定其他 Provider，则使用官方 SDK
        if "glm" in target_model.lower() and "openai/" not in target_model:
            async for chunk in self.zhipu_client.stream_chat(messages, target_model, **kwargs):
                yield chunk
            return

        # 针对 Ollama 模型做特殊处理
        if target_model.startswith("ollama/"):
            kwargs["api_base"] = settings.OLLAMA_BASE_URL
        elif settings.OPENAI_BASE_URL and "/" not in target_model:
            kwargs["api_base"] = settings.OPENAI_BASE_URL

        try:
            logger.info(f"正在向 LiteLLM 发送流式请求, Model: {target_model}")
            response = await litellm.acompletion(
                model=target_model,
                messages=messages,
                stream=True,
                timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
                **kwargs
            )
            async for chunk in response:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
        except asyncio.TimeoutError as e:
            raise LLMError(
                f"模型 {target_model} 请求超时",
                error_type="timeout",
                retryable=True,
                data={"model": target_model},
            ) from e
        except Exception as e:
            logger.error(f"LiteLLM 流式请求失败: {str(e)}")
            message = str(e)
            lower = message.lower()
            if "401" in lower or "authentication" in lower or "api key" in lower:
                error_type, retryable = "authentication", False
            elif "429" in lower or "rate limit" in lower:
                error_type, retryable = "rate_limit", True
            elif "timeout" in lower:
                error_type, retryable = "timeout", True
            else:
                error_type, retryable = "provider_error", True
            raise LLMError(
                f"模型 {target_model} 调用失败: {message}",
                error_type=error_type,
                retryable=retryable,
                data={"model": target_model},
            ) from e
