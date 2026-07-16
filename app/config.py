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

    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    database_path: str = "data/rag.sqlite3"
    index_dir: str = "data/index"
    source_base_url: str = "https://www.thss.tsinghua.edu.cn/"
    python_image: str = "python:3.10-slim"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
