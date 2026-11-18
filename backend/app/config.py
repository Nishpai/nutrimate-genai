"""Settings from environment variables, with the project .env file as a fallback.
Secrets (database password, JWT secret, Gemini key) are never written in code."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from nutrimate_core.paths import ROOT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "nutrimate_ai"
    mysql_password: str = ""
    mysql_database: str = "nutrimate_ai"
    mysql_pool_size: int = 10

    jwt_secret: str = ""
    jwt_expire_minutes: int = 60 * 24

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_fallback_models: str = "gemini-3.8-flash"
    gemini_timeout_seconds: int = 30
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_upload_mb: int = 4096
    reranker: str = "auto"  # auto (decided by the evaluation), on or off
    load_models: bool = True  # tests can turn the ML engine off to start faster

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.gemini_api_key.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    if not s.jwt_secret or len(s.jwt_secret) < 32:
        raise RuntimeError("JWT_SECRET is missing or shorter than 32 characters. Set it in .env.")
    return s
