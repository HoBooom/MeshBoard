"""
MeshBoard — Seed Data

개발/테스트를 위한 초기 사용자 데이터 생성.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
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
        "roles": ["agent_owner", "agent_engineer"],
    },
    {
        "name": "운영자",
        "email": "ops@meshboard.io",
        "login_id": "operator",
        "password": "ops1234",
        "roles": ["trust_ops", "release_manager"],
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
            password_changed = not verify_password(
                user_data["password"], user.password_hash
            )
            if password_changed:
                user.password_hash = hash_password(user_data["password"])

            role_result = await session.execute(
                select(UserRole).where(UserRole.user_id == user.user_id)
            )
            existing_role_entries = list(role_result.scalars().all())
            existing_roles = {entry.role for entry in existing_role_entries}
            target_roles = set(user_data["roles"])
            stale_roles = [
                entry for entry in existing_role_entries if entry.role not in target_roles
            ]
            for role_entry in stale_roles:
                await session.delete(role_entry)
            missing_roles = [
                role for role in user_data["roles"] if role not in existing_roles
            ]
            for role in missing_roles:
                session.add(UserRole(user_id=user.user_id, role=role))
            if stale_roles or missing_roles or password_changed:
                changes = []
                if stale_roles or missing_roles:
                    changes.append(
                        f"역할 추가: {', '.join(missing_roles) or '-'} / "
                        f"제거: {', '.join(entry.role for entry in stale_roles) or '-'}"
                    )
                if password_changed:
                    changes.append("데모 비밀번호 재동기화")
                print(
                    f"  🔄 계정 동기화: {user_data['email']} "
                    f"({'; '.join(changes)})"
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
