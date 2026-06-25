from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    OPENAI_API_KEY: str = ""
    LANGCHAIN_API_KEY: str = ""
    PG_VECTOR_PASSWORD: str = "postgres"

    OPENAI_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"
    MODEL_NAME: str = "glm-5.1"

    REDIS_URL: str = "redis://localhost:6379/0"
    SESSION_TTL: int = 86400

    PG_VECTOR_HOST: str = "127.0.0.1"
    PG_VECTOR_PORT: int = 5432
    PG_VECTOR_USER: str = "postgres"
    PG_VECTOR_DB: str = "ai-rag-knowledge"
    PG_VECTOR_COLLECTION_NAME: str = "kita_agent_docs"

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"

    RERANKER_API_URL: str = "http://localhost:7997/rerank"

    LANGCHAIN_TRACING_V2: str = "false"
    LANGCHAIN_PROJECT: str = "kita-agent"
    OBSERVABILITY_ENABLED: bool = True
    TRACE_PATH: str = "logs/agent_traces.jsonl"
    BAD_CASE_PATH: str = "logs/bad_cases.jsonl"
    MCP_ENABLED: bool = False

    @property
    def pg_database_url(self) -> str:
        return f"postgresql+psycopg2://{self.PG_VECTOR_USER}:{self.PG_VECTOR_PASSWORD}@{self.PG_VECTOR_HOST}:{self.PG_VECTOR_PORT}/{self.PG_VECTOR_DB}"

# 实例化全局配置对象
settings = Settings()
