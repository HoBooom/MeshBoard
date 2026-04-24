"""
MeshBoard — Application Settings

pydantic-settings 기반 환경 설정.
.env 파일 또는 환경 변수에서 값을 읽어옵니다.
"""

from __future__ import annotations

import json
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://meshboard:dev_password@localhost:5432/meshboard"

    # ── JWT ───────────────────────────────────────────────────
    JWT_SECRET_KEY: str = "meshboard-dev-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── CORS ──────────────────────────────────────────────────
    CORS_ORIGINS: str = '["http://localhost:5173"]'

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS_ORIGINS JSON string into a list."""
        return json.loads(self.CORS_ORIGINS)

    # ── LLM Configuration ─────────────────────────────────────
    RUNYOUR_API_KEY: str = ""

settings = Settings()
