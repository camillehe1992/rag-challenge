from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "THSS RAG Chatbot"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    demo_username: str = "admin"
    demo_password: str = "change-me"
    session_secret: str = "dev-session-secret"
    session_ttl_seconds: int = 60 * 60 * 8
    cookie_secure: bool = False
    cors_allow_origins: str = "http://localhost:8000,https://localhost:8443"

    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_timeout_seconds: float = 30.0

    database_path: str = "data/rag.sqlite3"
    index_dir: str = "data/index"
    source_base_url: str = "https://www.thss.tsinghua.edu.cn/"
    python_image: str = "python:3.10-slim"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return [item.strip() for item in self.cors_allow_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
