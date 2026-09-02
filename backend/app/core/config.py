"""
MeshBoard — Application Settings

pydantic-settings 기반 환경 설정.
.env 파일 또는 환경 변수에서 값을 읽어옵니다.
"""

from __future__ import annotations

import json
from typing import List, Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEVELOPMENT_JWT_SECRET = "meshboard-dev-secret-key-change-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENVIRONMENT: Literal["development", "test", "production"] = "development"

    # ── Database ──────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://meshboard:dev_password@localhost:5432/meshboard"

    # ── JWT ───────────────────────────────────────────────────
    JWT_SECRET_KEY: str = DEVELOPMENT_JWT_SECRET
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── CORS ──────────────────────────────────────────────────
    CORS_ORIGINS: str = '["http://localhost:5173"]'

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS_ORIGINS JSON string into a list."""
        try:
            origins = json.loads(self.CORS_ORIGINS)
        except json.JSONDecodeError as exc:
            raise ValueError("CORS_ORIGINS must be a JSON array of origins") from exc
        if not isinstance(origins, list) or not all(isinstance(origin, str) for origin in origins):
            raise ValueError("CORS_ORIGINS must be a JSON array of strings")
        return origins

    # ── LLM Configuration ─────────────────────────────────────
    RUNYOUR_API_KEY: str = ""
    RUNYOUR_BASE_URL: str = "https://api.runyour.ai/v1"
    DEFAULT_LLM_MODEL: str = "openai/gpt-5"

    # ── 로컬 Qwen (OpenSynCity 에이전트 자연어 narration) ────────
    # 팀원들이 쓴 로컬 Qwen과 동일하게, OpenSynCity(outage_mpc_mesh) 에이전트 발언을 로컬 LLM이
    # 생성한다. Ollama / vLLM / LM Studio 등 OpenAI 호환 /v1 엔드포인트를 가리킨다.
    # 활성화하려면 MESH_LLM_NARRATION_ENABLED=true 로 켜고 base_url/model을 본인 환경에 맞춘다.
    # (꺼져 있으면 노트북과 동일한 결정론적 템플릿 문장을 사용 → Qwen 없이도 동작)
    MESH_LLM_NARRATION_ENABLED: bool = False
    QWEN_BASE_URL: str = "http://localhost:11434/v1"   # Ollama 기본
    QWEN_API_KEY: str = "ollama"                        # 로컬 서버는 보통 키 불필요(placeholder)
    QWEN_MODEL: str = "qwen2.5:7b"
    QWEN_TIMEOUT_SECONDS: float = 20.0
    QWEN_MAX_CONCURRENCY: int = 8                       # step당 다수 에이전트 동시 호출 상한

    # ── Agent broker safeguards ──────────────────────────────
    AGENT_INVOKE_TIMEOUT_SECONDS: float = 90.0
    AGENT_INVOKE_MAX_CONCURRENCY: int = 4

    # ── External MCP/Tool Configuration ───────────────────────
    # JSON array. Example:
    # [{"id":"company_search","name":"Company Search","description":"Search company API","url":"https://...","method":"POST","inputSchema":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}]
    EXTERNAL_MCP_TOOLS: str = "[]"

    @model_validator(mode="after")
    def validate_deployment_security(self) -> "Settings":
        """Fail fast when local-only defaults leak into a production deployment."""
        if self.AGENT_INVOKE_TIMEOUT_SECONDS <= 0:
            raise ValueError("AGENT_INVOKE_TIMEOUT_SECONDS must be greater than zero")
        if self.AGENT_INVOKE_MAX_CONCURRENCY < 1:
            raise ValueError("AGENT_INVOKE_MAX_CONCURRENCY must be at least one")
        if self.ENVIRONMENT == "production":
            if self.JWT_SECRET_KEY == DEVELOPMENT_JWT_SECRET or len(self.JWT_SECRET_KEY) < 32:
                raise ValueError(
                    "Production requires a non-default JWT_SECRET_KEY with at least 32 characters"
                )
            if "*" in self.cors_origins_list:
                raise ValueError("Production CORS_ORIGINS cannot contain '*'")
        return self

settings = Settings()
