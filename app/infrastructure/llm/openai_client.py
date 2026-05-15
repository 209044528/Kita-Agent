import time
import logging
from openai import OpenAI
from app.core.config import settings
from app.domain.agent.repository import ILlmService

logger = logging.getLogger(__name__)

class OpenAILlmServiceImpl(ILlmService):
    def __init__(self):
        base_client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL
        )

        if settings.LANGCHAIN_TRACING_V2.lower() == "true":
            try:
                from langsmith import wrappers
                self.client = wrappers.wrap_openai(base_client)
                logger.info("LangSmith tracing enabled for OpenAI client")
            except ImportError:
                logger.warning("langsmith not installed, tracing disabled")
                self.client = base_client
        else:
            self.client = base_client

        self.model_name = settings.MODEL_NAME
        self.last_call_time = 0.0

    def generate_reply(self, messages: list) -> str:
        for attempt in range(3):
            current_time = time.time()
            elapsed_time = current_time - self.last_call_time

            if self.last_call_time > 0 and elapsed_time < 20.0:
                wait_time = 20.0 - elapsed_time
                logger.info(f"触发 API 频率限制，挂起等待 {wait_time:.1f} 秒")
                time.sleep(wait_time)

            self.last_call_time = time.time()
            try:
                logger.info(f"正在向 LLM 发送请求 (尝试 {attempt + 1}/3)")
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=0.7
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                if attempt == 2:
                    logger.error(f"LLM 请求失败，已达最大重试次数: {str(e)}")
                    return f"系统错误: {str(e)}"
                logger.warning(f"请求失败，准备重试: {str(e)}")
                time.sleep(2)