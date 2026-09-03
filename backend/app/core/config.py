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
    # 기본값은 **로컬 OpenAI-호환 서버**(Ollama)를 가리킨다. 유료 API 호출이 발생하지 않으며,
    # 클론한 사람이 키 없이 바로 실행할 수 있다.
    # 다른 백엔드로 갈아끼우려면 아래 세 값만 바꾸면 된다 (vLLM / LM Studio / OpenAI / 게이트웨이 등).
    LLM_BASE_URL: str = "http://localhost:11434/v1"
    LLM_API_KEY: str = "ollama"  # 로컬 서버는 키를 무시한다. SDK가 빈 값을 거부하므로 placeholder.
    LLM_MODEL: str = "qwen3:8b"
    LLM_TIMEOUT_SECONDS: float = 120.0
    LLM_MAX_OUTPUT_TOKENS: int = 4096
    # 모델명을 그대로 전달할지 여부. Ollama는 "qwen2.5:7b" 처럼 provider 접두가 없고,
    # OpenRouter 계열 게이트웨이는 "openai/gpt-4o" 처럼 접두를 요구한다.
    # JSON 객체로 별칭을 정의하면 호출 시 치환된다. 예: {"fast":"qwen2.5:3b"}
    LLM_MODEL_ALIASES: str = "{}"

    # ── 외부 게이트웨이 (선택) ─────────────────────────────────
    # RUNYOUR_API_KEY 를 채우면 위 LLM_* 대신 이 게이트웨이를 사용한다.
    # 로컬 모델만 쓸 경우 비워두면 되고, 그때는 어떤 유료 호출도 발생하지 않는다.
    RUNYOUR_API_KEY: str = ""
    RUNYOUR_BASE_URL: str = "https://api.runyour.ai/v1"
    RUNYOUR_MODEL: str = "openai/gpt-5"
    MODEL_PRICING_USD_PER_MILLION: str = "{}"

    @property
    def llm_uses_external_gateway(self) -> bool:
        """유료 게이트웨이가 명시적으로 설정됐는지. 비어 있으면 로컬 전용으로 동작한다."""
        return bool(self.RUNYOUR_API_KEY.strip())

    @property
    def llm_base_url(self) -> str:
        return self.RUNYOUR_BASE_URL if self.llm_uses_external_gateway else self.LLM_BASE_URL

    @property
    def llm_api_key(self) -> str:
        # 로컬 서버는 키를 검사하지 않지만 OpenAI SDK가 빈 문자열을 거부하므로 placeholder를 보장한다.
        return self.RUNYOUR_API_KEY if self.llm_uses_external_gateway else (self.LLM_API_KEY or "local")

    @property
    def llm_default_model(self) -> str:
        return self.RUNYOUR_MODEL if self.llm_uses_external_gateway else self.LLM_MODEL

    @property
    def llm_model_aliases(self) -> dict[str, str]:
        """호출 시 치환할 모델 별칭. 잘못된 JSON은 조용히 무시하지 않고 명시적으로 실패한다."""
        try:
            aliases = json.loads(self.LLM_MODEL_ALIASES)
        except json.JSONDecodeError as exc:
            raise ValueError("LLM_MODEL_ALIASES must be valid JSON") from exc
        if not isinstance(aliases, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in aliases.items()
        ):
            raise ValueError("LLM_MODEL_ALIASES must be a JSON object of string pairs")
        return aliases

    @property
    def model_pricing(self) -> dict[str, dict[str, float]]:
        """Optional per-million-token rates, kept outside source control."""
        try:
            pricing = json.loads(self.MODEL_PRICING_USD_PER_MILLION)
        except json.JSONDecodeError as exc:
            raise ValueError("MODEL_PRICING_USD_PER_MILLION must be valid JSON") from exc
        if not isinstance(pricing, dict):
            raise ValueError("MODEL_PRICING_USD_PER_MILLION must be a JSON object")
        normalized: dict[str, dict[str, float]] = {}
        for model, rates in pricing.items():
            if not isinstance(model, str) or not isinstance(rates, dict):
                raise ValueError("Each model price must be an object")
            try:
                input_rate = float(rates["input"])
                output_rate = float(rates["output"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Each model price requires numeric input/output rates") from exc
            if input_rate < 0 or output_rate < 0:
                raise ValueError("Model prices cannot be negative")
            normalized[model] = {"input": input_rate, "output": output_rate}
        return normalized

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
    # 로컬 7B 모델은 첫 호출에 수십 초가 걸릴 수 있다. LLM_TIMEOUT_SECONDS(120) 보다 크게 두어
    # HTTP timeout 이 먼저 나고 broker 취소는 최후의 안전망이 되도록 한다.
    AGENT_INVOKE_TIMEOUT_SECONDS: float = 180.0
    AGENT_INVOKE_MAX_CONCURRENCY: int = 4

    # ── External MCP/Tool Configuration ───────────────────────
    # JSON array. Example:
    # [{"id":"company_search","name":"Company Search","description":"Search company API","url":"https://...","method":"POST","inputSchema":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}]
    EXTERNAL_MCP_TOOLS: str = "[]"

    # ── Security event connector ─────────────────────────────
    SECURITY_WEBHOOK_URL: str = ""
    SECURITY_WEBHOOK_SECRET: str = ""
    SECURITY_WEBHOOK_TIMEOUT_SECONDS: float = 5.0

    @model_validator(mode="after")
    def validate_deployment_security(self) -> "Settings":
        """Fail fast when local-only defaults leak into a production deployment."""
        if self.AGENT_INVOKE_TIMEOUT_SECONDS <= 0:
            raise ValueError("AGENT_INVOKE_TIMEOUT_SECONDS must be greater than zero")
        if self.AGENT_INVOKE_MAX_CONCURRENCY < 1:
            raise ValueError("AGENT_INVOKE_MAX_CONCURRENCY must be at least one")
        if self.SECURITY_WEBHOOK_TIMEOUT_SECONDS <= 0:
            raise ValueError("SECURITY_WEBHOOK_TIMEOUT_SECONDS must be greater than zero")
        if self.ENVIRONMENT == "production":
            if self.JWT_SECRET_KEY == DEVELOPMENT_JWT_SECRET or len(self.JWT_SECRET_KEY) < 32:
                raise ValueError(
                    "Production requires a non-default JWT_SECRET_KEY with at least 32 characters"
                )
            if "*" in self.cors_origins_list:
                raise ValueError("Production CORS_ORIGINS cannot contain '*'")
            if self.SECURITY_WEBHOOK_URL and not self.SECURITY_WEBHOOK_URL.startswith("https://"):
                raise ValueError("Production SECURITY_WEBHOOK_URL must use HTTPS")
        return self

settings = Settings()
