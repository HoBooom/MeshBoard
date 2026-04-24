"""
MeshBoard — Auth API Endpoints

인증, 사용자 등록, 토큰 갱신 API.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.rbac import RequireRoles
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _build_token_payload(user: User) -> dict:
    """JWT 페이로드를 구성합니다."""
    return {
        "sub": str(user.user_id),
        "email": user.email,
        "name": user.name,
        "roles": user.roles,
    }


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    사용자 등록 (개발 환경용).

    실제 운영 환경에서는 OIDC 연동으로 대체됩니다.
    """
    # 이메일 중복 확인
    existing = await db.execute(
        select(User).where((User.email == body.email) | (User.login_id == body.login_id))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 등록된 이메일 또는 로그인 ID입니다.",
        )

    # 역할 유효성 검증
    valid_roles = {
        "agent_owner", "agent_engineer", "trust_ops",
        "governance", "evaluator", "ethics_liaison", "release_manager",
    }
    for role in body.roles:
        if role not in valid_roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"유효하지 않은 역할: {role}. 가능한 역할: {', '.join(sorted(valid_roles))}",
            )

    # 사용자 생성
    user = User(
        name=body.name,
        email=body.email,
        login_id=body.login_id,
        password_hash=hash_password(body.password),
        state="ACTIVE",
    )
    db.add(user)
    await db.flush()  # user_id 생성을 위해 flush

    # 역할 할당
    for role in body.roles:
        db.add(UserRole(user_id=user.user_id, role=role))

    await db.flush()

    # selectinload로 역할 정보 포함하여 반환
    stmt = (
        select(User)
        .options(selectinload(User.role_entries))
        .where(User.user_id == user.user_id)
    )
    result = await db.execute(stmt)
    user = result.scalar_one()

    return UserResponse(
        user_id=user.user_id,
        name=user.name,
        email=user.email,
        login_id=user.login_id,
        state=user.state,
        roles=user.roles,
        created_at=user.created_at,
        last_login=user.last_login,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    이메일/비밀번호 로그인 → JWT 토큰 발급.

    반환된 JWT에는 사용자 ID, 이메일, 이름, 역할이 포함됩니다.
    """
    # 사용자 조회
    stmt = (
        select(User)
        .options(selectinload(User.role_entries))
        .where(User.email == body.email)
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
        )

    if user.state != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비활성화된 계정입니다.",
        )

    # 마지막 로그인 시각 업데이트
    user.last_login = datetime.now(timezone.utc)

    # JWT 토큰 발급
    payload = _build_token_payload(user)
    access_token = create_access_token(payload)
    refresh_token = create_refresh_token(payload)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
):
    """현재 로그인된 사용자 정보 및 역할 조회."""
    return UserResponse(
        user_id=current_user.user_id,
        name=current_user.name,
        email=current_user.email,
        login_id=current_user.login_id,
        state=current_user.state,
        roles=current_user.roles,
        created_at=current_user.created_at,
        last_login=current_user.last_login,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """Refresh 토큰을 사용하여 새로운 Access/Refresh 토큰을 발급합니다."""
    payload = decode_token(body.refresh_token)

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 Refresh 토큰입니다.",
        )

    user_id = payload.get("sub")
    stmt = (
        select(User)
        .options(selectinload(User.role_entries))
        .where(User.user_id == user_id)
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None or user.state != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자를 찾을 수 없거나 비활성 상태입니다.",
        )

    new_payload = _build_token_payload(user)
    return TokenResponse(
        access_token=create_access_token(new_payload),
        refresh_token=create_refresh_token(new_payload),
    )


# ── RBAC 검증용 테스트 엔드포인트 ──────────────────────────────

@router.get(
    "/admin-only",
    dependencies=[Depends(RequireRoles("governance", "trust_ops"))],
)
async def admin_only_endpoint(
    current_user: User = Depends(get_current_user),
):
    """
    거버넌스/운영 전용 엔드포인트.

    권한이 없는 사용자는 403 Forbidden을 받습니다.
    """
    return {
        "message": f"안녕하세요, {current_user.name}님! 관리자 전용 페이지에 접근하셨습니다.",
        "roles": current_user.roles,
    }
