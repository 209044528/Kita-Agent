from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    OPENAI_API_KEY: str = ""
    LANGCHAIN_API_KEY: str = ""
    PG_VECTOR_PASSWORD: str = "postgres"

    OPENAI_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"
    MODEL_NAME: str = "glm-5.1"
    MODEL_FALLBACKS: str = ""
    LLM_FIRST_PACKET_TIMEOUT_SECONDS: float = 30.0
    LLM_REQUEST_TIMEOUT_SECONDS: float = 120.0
    LLM_FAILURE_THRESHOLD: int = 2
    LLM_CIRCUIT_OPEN_SECONDS: int = 30

    REDIS_URL: str = "redis://localhost:6379/0"
    SESSION_TTL: int = 86400
    SESSION_LOCK_TTL_SECONDS: int = 300
    TASK_TTL_SECONDS: int = 1800
    TOOL_TIMEOUT_SECONDS: float = 30.0

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
    PLATFORM_DB_PATH: str = "data/kita_platform.db"
    MCP_ENABLED: bool = False
    MCP_CLIENT_SERVERS: str = ""
    SUMMARY_TRIGGER_MESSAGES: int = 10
    SUMMARY_KEEP_RECENT_MESSAGES: int = 6

    AUTH_ENABLED: bool = False
    AUTH_API_KEYS: str = ""
    CORS_ORIGINS: str = "http://localhost:8000,http://127.0.0.1:8000"

    MAX_UPLOAD_BYTES: int = 20 * 1024 * 1024
    ALLOWED_UPLOAD_EXTENSIONS: str = ".txt,.md,.pdf,.doc,.docx,.json,.yaml,.yml"
    GIT_ALLOWED_HOSTS: str = "github.com,gitee.com,gitlab.com"
    GIT_MAX_FILES: int = 5000
    GIT_MAX_TOTAL_BYTES: int = 50 * 1024 * 1024
    GIT_MAX_FILE_BYTES: int = 2 * 1024 * 1024
    GIT_CLONE_TIMEOUT_SECONDS: int = 120

    @field_validator("AUTH_API_KEYS")
    @classmethod
    def validate_auth_keys(cls, value: str) -> str:
        for item in filter(None, (part.strip() for part in value.split(","))):
            parts = item.split(":")
            if len(parts) < 2:
                raise ValueError(
                    "AUTH_API_KEYS must use api-key:user-id[:role] entries"
                )
        return value

    @property
    def pg_database_url(self) -> str:
        return f"postgresql+psycopg2://{self.PG_VECTOR_USER}:{self.PG_VECTOR_PASSWORD}@{self.PG_VECTOR_HOST}:{self.PG_VECTOR_PORT}/{self.PG_VECTOR_DB}"

    @property
    def model_candidates(self) -> list[str]:
        candidates = [self.MODEL_NAME]
        candidates.extend(
            item.strip() for item in self.MODEL_FALLBACKS.split(",") if item.strip()
        )
        return list(dict.fromkeys(candidates))

    @property
    def auth_key_map(self) -> dict[str, tuple[str, str]]:
        result: dict[str, tuple[str, str]] = {}
        for item in filter(None, (part.strip() for part in self.AUTH_API_KEYS.split(","))):
            api_key, user_id, *role = item.split(":")
            result[api_key] = (user_id, role[0] if role else "user")
        return result

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.CORS_ORIGINS.split(",") if item.strip()]

    @property
    def allowed_upload_extensions(self) -> set[str]:
        return {
            item.strip().lower()
            for item in self.ALLOWED_UPLOAD_EXTENSIONS.split(",")
            if item.strip()
        }

    @property
    def git_allowed_hosts(self) -> set[str]:
        return {
            item.strip().lower()
            for item in self.GIT_ALLOWED_HOSTS.split(",")
            if item.strip()
        }

# 实例化全局配置对象
settings = Settings()
