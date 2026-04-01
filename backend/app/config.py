from __future__ import annotations

from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_ENV: str = "development"
    APP_URL: str = "http://localhost:8000"
    SECRET_KEY: str = "replace-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_HOURS: int = 24

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/emailagent"
    DATABASE_URL_PSYCOPG: str = "postgresql://postgres:postgres@localhost:5432/emailagent"

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/auth/callback"

    TOKEN_ENCRYPTION_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    TAVILY_API_KEY: str = ""
    FRONTEND_URL: str = "http://localhost:3000"
    LANGSMITH_TRACING: bool = False
    LANGSMITH_PROJECT: str = "email-agent"
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGSMITH_API_KEY: str = ""

    @property
    def sync_database_url(self) -> str:
        return self.DATABASE_URL_PSYCOPG


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
