"""
MeshBoard — Role-Based Access Control (RBAC)

역할 기반 접근 제어 의존성 함수.
"""

from __future__ import annotations

from functools import wraps
from typing import Callable, Sequence

from fastapi import Depends, HTTPException, status

from app.core.security import get_current_user


class RequireRoles:
    """
    역할 기반 접근 제어 의존성 클래스.

    사용 예:
        @router.get("/admin", dependencies=[Depends(RequireRoles("governance", "trust_ops"))])
        async def admin_endpoint():
            ...
    """

    def __init__(self, *roles: str):
        self.required_roles = set(roles)

    async def __call__(self, current_user=Depends(get_current_user)):
        user_roles = {r.role for r in current_user.role_entries}

        if not self.required_roles.intersection(user_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"이 작업에는 다음 역할 중 하나가 필요합니다: {', '.join(self.required_roles)}",
            )
        return current_user


def require_roles(*roles: str):
    """
    역할 기반 접근 제어 의존성 팩토리.

    사용 예:
        @router.get("/admin", dependencies=[Depends(require_roles("governance"))])
        async def admin_endpoint():
            ...
    """
    return RequireRoles(*roles)
