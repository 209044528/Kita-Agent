from zhipuai import ZhipuAI
from loguru import logger
from app.core.config import settings
from app.domain.agent.repository import ILLMClient

class ZhipuAIClient(ILLMClient):
    def __init__(self):
        self.client = ZhipuAI(api_key=settings.OPENAI_API_KEY)  # 智谱通常复用 OPENAI_API_KEY 变量
        self.default_model = settings.MODEL_NAME

    async def chat(self, messages: list, model: str = None, **kwargs) -> str:
        target_model = model or self.default_model
        
        # 移除可能存在的提供商前缀
        if "/" in target_model:
            target_model = target_model.split("/")[-1]

        try:
            logger.info(f"正在向 ZhipuAI SDK 发送请求, Model: {target_model}")
            # 注意：ZhipuAI 的异步调用方式是 client.chat.asyncCompletions，
            # 但通常我们使用同步调用配合 asyncio 运行，或者使用其提供的异步客户端。
            # 这里为了简单直接使用同步调用（在异步环境下建议用 run_in_executor 或异步版本）
            # 根据最新 SDK，支持 completions.create
            response = self.client.chat.completions.create(
                model=target_model,
                messages=messages,
                **kwargs
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"ZhipuAI 请求失败: {str(e)}")
            return f"系统错误: {str(e)}"
