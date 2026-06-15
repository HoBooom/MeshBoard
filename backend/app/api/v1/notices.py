from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException

from app.db.session import get_db
from app.models.notice import Notice
from app.schemas.notice import (
    NOTICE_CATEGORIES,
    NOTICE_PRIORITIES,
    NoticeCreate,
    NoticeRead,
)
from app.core.security import get_current_user
from app.schemas.auth import UserResponse
from app.core.rbac import RequireRoles

router = APIRouter(prefix="/notices", tags=["notices"])

# 우선순위 정렬 가중치 (critical 이 가장 위로)
_PRIORITY_ORDER = {"critical": 0, "high": 1, "normal": 2}

@router.post("/", response_model=NoticeRead, status_code=status.HTTP_201_CREATED)
async def create_notice(
    notice_in: NoticeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(RequireRoles("admin", "governance", "trust_ops", "release_manager"))
):
    """
    공지사항 생성 (관리자/거버넌스/운영자/릴리스관리자 권한 필요).
    """
    if notice_in.category not in NOTICE_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"category 는 {sorted(NOTICE_CATEGORIES)} 중 하나여야 합니다.",
        )
    if notice_in.priority not in NOTICE_PRIORITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"priority 는 {sorted(NOTICE_PRIORITIES)} 중 하나여야 합니다.",
        )

    new_notice = Notice(
        title=notice_in.title,
        body=notice_in.body,
        target_role=notice_in.target_role,
        is_active=notice_in.is_active,
        category=notice_in.category,
        priority=notice_in.priority,
        pinned=notice_in.pinned,
        expires_at=notice_in.expires_at,
        created_by=current_user.user_id,
    )
    db.add(new_notice)
    await db.commit()
    await db.refresh(new_notice)
    return new_notice

@router.get("/", response_model=List[NoticeRead])
async def get_notices(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    현재 로그인한 사용자에게 해당하는 유효한 공지사항 목록 조회.
    """
    now = datetime.now(timezone.utc)
    
    # target_role이 'all' 이거나 현재 사용자의 roles 중 하나와 일치하는지 필터링
    stmt = select(Notice).where(
        Notice.is_active == True,
        Notice.target_role.in_(["all", "admin"] + current_user.roles),
        (Notice.expires_at.is_(None)) | (Notice.expires_at > now)
    )

    result = await db.execute(stmt)
    notices = list(result.scalars().all())

    # 고정 공지 → 우선순위(critical>high>normal) → 최신순
    notices.sort(
        key=lambda n: (
            not n.pinned,
            _PRIORITY_ORDER.get(n.priority, 99),
            -n.created_at.timestamp(),
        )
    )
    return notices
