"""
MeshBoard — Seed Data

개발/테스트를 위한 초기 사용자 데이터 생성.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.session import async_session_factory
from app.models.user import User, UserRole

SEED_USERS = [
    {
        "name": "관리자",
        "email": "admin@meshboard.io",
        "login_id": "admin",
        "password": "admin1234",
        "roles": ["governance", "trust_ops"],
    },
    {
        "name": "개발자",
        "email": "dev@meshboard.io",
        "login_id": "developer",
        "password": "dev1234",
        "roles": ["agent_owner", "agent_engineer", "trust_ops", "release_manager"],
    },
    {
        "name": "운영자",
        "email": "ops@meshboard.io",
        "login_id": "operator",
        "password": "ops1234",
        "roles": ["trust_ops", "release_manager", "agent_owner", "agent_engineer"],
    },
    {
        "name": "평가자",
        "email": "user@meshboard.io",
        "login_id": "evaluator",
        "password": "user1234",
        "roles": ["evaluator"],
    },
]


async def seed_users(session: AsyncSession) -> None:
    """시드 사용자 데이터를 생성합니다."""
    for user_data in SEED_USERS:
        # 이미 존재하는지 확인
        result = await session.execute(
            select(User).where(User.email == user_data["email"])
        )
        user = result.scalar_one_or_none()
        if user:
            role_result = await session.execute(
                select(UserRole.role).where(UserRole.user_id == user.user_id)
            )
            existing_roles = set(role_result.scalars().all())
            missing_roles = [
                role for role in user_data["roles"] if role not in existing_roles
            ]
            for role in missing_roles:
                session.add(UserRole(user_id=user.user_id, role=role))
            if missing_roles:
                print(
                    f"  🔄 역할 추가: {user_data['email']} "
                    f"({', '.join(missing_roles)})"
                )
            else:
                print(f"  ⏭  이미 존재: {user_data['email']}")
            continue

        user = User(
            name=user_data["name"],
            email=user_data["email"],
            login_id=user_data["login_id"],
            password_hash=hash_password(user_data["password"]),
            state="ACTIVE",
        )
        session.add(user)
        await session.flush()

        for role in user_data["roles"]:
            session.add(UserRole(user_id=user.user_id, role=role))

        print(f"  ✅ 생성: {user_data['email']} (역할: {', '.join(user_data['roles'])})")

    await session.commit()


async def main() -> None:
    """시드 데이터 실행 진입점."""
    print("🌱 MeshBoard 시드 데이터 생성 시작...")
    async with async_session_factory() as session:
        await seed_users(session)
    print("🌱 시드 데이터 생성 완료!")


if __name__ == "__main__":
    asyncio.run(main())
