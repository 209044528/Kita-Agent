import os
import litellm
from loguru import logger
from app.core.config import settings
from app.domain.agent.repository import ILLMClient
from app.infrastructure.llm.zhipuai_client import ZhipuAIClient

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

    async def chat(self, messages: list, model: str = None, **kwargs) -> str:
        target_model = model or self.default_model

        # 如果是 GLM 模型，且没有显式指定其他 Provider，则使用官方 SDK
        if "glm" in target_model.lower() and "openai/" not in target_model:
            return await self.zhipu_client.chat(messages, target_model, **kwargs)

        # 针对 Ollama 模型做特殊处理
        if target_model.startswith("ollama/"):
            kwargs["api_base"] = settings.OLLAMA_BASE_URL
        elif settings.OPENAI_BASE_URL and "/" not in target_model:
            kwargs["api_base"] = settings.OPENAI_BASE_URL

        try:
            logger.info(f"正在向 LiteLLM 发送请求, Model: {target_model}")
            response = await litellm.acompletion(
                model=target_model,
                messages=messages,
                **kwargs
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"LiteLLM 请求失败: {str(e)}")
            return f"系统错误: {str(e)}"

