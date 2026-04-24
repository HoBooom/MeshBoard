import asyncio
from app.db.session import async_session_maker
from app.models.notice import Notice
from app.models.user import User
from sqlalchemy import select
from datetime import datetime, timezone

async def seed_notices():
    async with async_session_maker() as db:
        admin = (await db.execute(select(User).where(User.email == "admin@meshboard.io"))).scalars().first()
        if not admin:
            print("Admin not found")
            return

        notices = [
            Notice(
                title="[전체공지] MeshBoard Phase 1 시스템 업데이트 안내",
                body="MeshBoard의 핵심 레지스트리 마이그레이션이 완료되었습니다. 이제 안정적인 데이터베이스 백엔드를 바탕으로 에이전트 개발을 시작하실 수 있습니다.",
                target_role="all",
                is_active=True,
                created_by=admin.user_id,
                created_at=datetime.now(timezone.utc)
            ),
            Notice(
                title="[운영자 전용] 시스템 점검 예정",
                body="이번 주 금요일 자정에 2시간 동안 정기 시스템 점검이 있을 예정입니다. Trust Ops 팀은 모니터링을 준비해 주시기 바랍니다.",
                target_role="trust_ops",
                is_active=True,
                created_by=admin.user_id,
                created_at=datetime.now(timezone.utc)
            ),
            Notice(
                title="[만료된 공지] 지난 주 서버 장애 보고서",
                body="지난 주 발생한 로그인 서버 지연 문제에 대한 사후 분석 보고서가 업로드되었습니다.",
                target_role="all",
                is_active=False, # Make it inactive
                created_by=admin.user_id,
                created_at=datetime.now(timezone.utc)
            )
        ]
        
        db.add_all(notices)
        await db.commit()
        print("Notices seeded successfully.")

if __name__ == "__main__":
    asyncio.run(seed_notices())
