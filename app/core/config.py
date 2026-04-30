from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = ""
    MODEL_NAME: str = ""

    REDIS_URL: str = "redis://localhost:6379/0"
    SESSION_TTL: int = 86400

    class Config:
        env_file = ".env"


settings = Settings()