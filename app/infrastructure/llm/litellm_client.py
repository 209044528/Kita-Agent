import os
import litellm
from loguru import logger
from app.core.config import settings
from app.domain.agent.repository import ILLMClient

class LiteLLMClient(ILLMClient):
    def __init__(self):
        # 配置 LiteLLM 环境变量
        os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
        os.environ["OPENAI_API_BASE"] = settings.OPENAI_BASE_URL
        
        # 如果有 Ollama 配置也可以设置
        # os.environ["OLLAMA_API_BASE"] = settings.OLLAMA_BASE_URL
        
        self.default_model = settings.MODEL_NAME
        
        # 允许 LiteLLM 在模型未找到时抛出异常
        litellm.drop_params = True

    async def chat(self, messages: list, model: str = None, **kwargs) -> str:
        target_model = model or self.default_model
        
        # 针对 Ollama 模型做特殊处理，如果 model_name 是 ollama/ 开头，
        # LiteLLM 会自动路由，但我们需要确保 base_url 正确
        if target_model.startswith("ollama/"):
            kwargs["api_base"] = settings.OLLAMA_BASE_URL

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
