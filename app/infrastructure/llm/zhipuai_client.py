import asyncio
from zhipuai import ZhipuAI
from loguru import logger
from typing import AsyncGenerator
from app.core.config import settings
from app.domain.agent.repository import ILLMClient
from app.core.exceptions import LLMError

class ZhipuAIClient(ILLMClient):
    def __init__(self):
        # 智谱 SDK 目前主要支持同步调用，我们在异步环境中使用 to_thread 包装
        self.client = ZhipuAI(api_key=settings.OPENAI_API_KEY)
        self.default_model = settings.MODEL_NAME

    async def stream_chat(self, messages: list, model: str = None, **kwargs) -> AsyncGenerator[str, None]:
        target_model = model or self.default_model
        if "/" in target_model:
            target_model = target_model.split("/")[-1]

        try:
            logger.info(f"正在向 ZhipuAI SDK 发送流式请求 (Sync in Thread), Model: {target_model}")
            # 在线程中启动流式请求
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=target_model,
                messages=messages,
                stream=True,
                **kwargs
            )

            # 迭代同步生成器
            iterator = iter(response)

            def safe_next():
                try:
                    return next(iterator)
                except StopIteration:
                    return None

            while True:
                chunk = await asyncio.to_thread(safe_next)
                if chunk is None:
                    break
                
                content = chunk.choices[0].delta.content
                if content:
                    yield content

        except Exception as e:
            logger.error(f"ZhipuAI 流式请求启动失败: {str(e)}")
            raise LLMError(
                f"智谱模型 {target_model} 调用失败: {e}",
                error_type="provider_error",
                retryable=True,
                data={"model": target_model},
            ) from e

