"""
MeshBoard — OIDC Abstraction Layer

기업 IdP 연동을 위한 추상화 레이어.
현재는 MockOIDCProvider로 로컬 인증을 제공하며,
추후 OktaProvider, AzureADProvider 등으로 교체 가능합니다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class OIDCUserInfo:
    """OIDC 인증 후 반환되는 사용자 정보."""
    sub: str           # OIDC subject identifier
    email: str
    name: str
    iss: str           # Issuer URL
    roles: list[str]   # 사용자 역할


class OIDCProvider(ABC):
    """OIDC Provider 인터페이스 — 모든 IdP 구현체가 따르는 계약."""

    @abstractmethod
    async def authenticate(self, token: str) -> Optional[OIDCUserInfo]:
        """
        IdP 토큰을 검증하고 사용자 정보를 반환합니다.
        검증 실패 시 None을 반환합니다.
        """
        ...

    @abstractmethod
    async def get_authorization_url(self, redirect_uri: str) -> str:
        """OIDC 인증 URL을 생성합니다."""
        ...

    @abstractmethod
    async def exchange_code(self, code: str, redirect_uri: str) -> Optional[OIDCUserInfo]:
        """Authorization code를 토큰으로 교환하고 사용자 정보를 반환합니다."""
        ...


class MockOIDCProvider(OIDCProvider):
    """
    개발/테스트용 Mock OIDC Provider.

    실제 IdP 없이 로컬 인증 흐름을 테스트할 수 있습니다.
    """

    async def authenticate(self, token: str) -> Optional[OIDCUserInfo]:
        """Mock 인증 — 개발 환경에서 항상 성공합니다."""
        return OIDCUserInfo(
            sub="mock-sub-001",
            email="mock@meshboard.io",
            name="Mock User",
            iss="https://mock-idp.meshboard.io",
            roles=["agent_owner"],
        )

    async def get_authorization_url(self, redirect_uri: str) -> str:
        """Mock 인증 URL — 로컬 콜백으로 바로 리다이렉트합니다."""
        return f"{redirect_uri}?code=mock-auth-code"

    async def exchange_code(self, code: str, redirect_uri: str) -> Optional[OIDCUserInfo]:
        """Mock 코드 교환 — 항상 성공합니다."""
        if code == "mock-auth-code":
            return await self.authenticate("mock-token")
        return None


# ── Provider Singleton ────────────────────────────────────────
# 실제 환경에서는 설정에 따라 다른 Provider 인스턴스를 생성합니다.
oidc_provider: OIDCProvider = MockOIDCProvider()
