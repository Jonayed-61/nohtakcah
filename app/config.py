from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "BUP CSE FEST 2026 - GridWise LLM"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "production"

    # LLM Settings
    LLM_PROVIDER: str = "google"
    LLM_MODEL: str = "gemini-2.5-flash"
    LLM_API_KEY: str = ""
    LLM_TIMEOUT_SECONDS: float = 12.0

    # Server Settings
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
