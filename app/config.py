from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "BUP CSE FEST 2026 - GridWise LLM"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "production"

    # LLM Settings
    LLM_PROVIDER: str = "groq"
    LLM_MODEL: str = "openai/gpt-oss-20b"
    LLM_API_KEY: str = ""
    LLM_TIMEOUT_SECONDS: float = 12.0

    # Server Settings
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    LOG_LEVEL: str = "INFO"

settings = Settings()
