"""Application configuration via environment variables."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "MCP Gateway"
    environment: str = Field(default="development")
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")
    secret_key: str = Field(default="change-me-in-production")

    # API server
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    cors_origins: list[str] = Field(default=["http://localhost:5173", "http://localhost:3000"])

    # PostgreSQL
    database_url: str = Field(
        default="postgresql+asyncpg://mcp_user:mcp_password@localhost:5432/mcp_gateway"
    )
    db_pool_size: int = Field(default=10)
    db_max_overflow: int = Field(default=20)

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")

    # LLM providers
    groq_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


settings = Settings()
