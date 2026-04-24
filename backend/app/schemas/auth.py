"""
MeshBoard — Auth Pydantic Schemas

인증 관련 요청/응답 스키마 정의.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# ── Request Schemas ───────────────────────────────────────────

class LoginRequest(BaseModel):
    """로그인 요청."""
    email: str = Field(..., description="사용자 이메일")
    password: str = Field(..., min_length=4, description="비밀번호")


class RegisterRequest(BaseModel):
    """사용자 등록 요청 (개발 환경용)."""
    name: str = Field(..., min_length=1, max_length=255, description="이름")
    email: str = Field(..., description="이메일")
    login_id: str = Field(..., min_length=3, max_length=50, description="로그인 ID")
    password: str = Field(..., min_length=4, description="비밀번호")
    roles: List[str] = Field(default=[], description="역할 목록")


class RefreshRequest(BaseModel):
    """토큰 갱신 요청."""
    refresh_token: str = Field(..., description="갱신 토큰")


# ── Response Schemas ──────────────────────────────────────────

class TokenResponse(BaseModel):
    """로그인 성공 시 반환되는 토큰 응답."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserRoleResponse(BaseModel):
    """역할 정보."""
    role: str
    granted_at: datetime


class UserResponse(BaseModel):
    """사용자 정보 응답."""
    user_id: UUID
    name: str
    email: str
    login_id: str
    state: str
    roles: List[str]
    created_at: datetime
    last_login: Optional[datetime] = None

    model_config = {"from_attributes": True}
