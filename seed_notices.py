"""MeshBoard — 홈 화면 공지 시드 데이터.

도시 전력 관리 시스템(CityLearn 기반 그리드 운영)의 운영 공지와
회사 내부 공지(거버넌스/릴리스/시스템/보안/일반)를 함께 적재한다.

멱등 실행: 기존 공지를 모두 제거한 뒤 다시 적재한다.
실행: cd backend && uv run python ../seed_notices.py
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.db.session import async_session_factory
from app.models.notice import Notice
from app.models.user import User


def _ago(days: int = 0, hours: int = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days, hours=hours)


def _ahead(days: int = 0, hours: int = 0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days, hours=hours)


async def seed_notices() -> None:
    async with async_session_factory() as db:
        admin = (
            await db.execute(select(User).where(User.email == "admin@meshboard.io"))
        ).scalars().first()
        if not admin:
            print("❌ admin@meshboard.io 사용자를 찾을 수 없습니다. 먼저 사용자 시드를 실행하세요.")
            return

        # 멱등성: 기존 공지 전체 삭제 후 재적재
        await db.execute(delete(Notice))

        notices = [
            # ── 도시 전력 관리 시스템 운영 공지 ─────────────────────────
            Notice(
                title="[전력경보] 여름철 피크 대응 — 자동 수요반응(DR) 모드 가동",
                body=(
                    "기상청 폭염 특보에 따라 오늘 14:00~17:00 도시 전력 수요가 연중 최고치에 도달할 것으로 "
                    "예측됩니다. City Grid Coordinator가 17개 빌딩의 ESS(배터리)를 자동 방전 모드로 전환하여 "
                    "피크 셰이빙을 수행합니다. 운영팀은 계통 부하율(net load) 대시보드를 상시 모니터링해 주십시오. "
                    "수동 개입이 필요한 경우 운영 콘솔 > 에이전트 운영 관리에서 해당 에이전트를 일시 중지할 수 있습니다."
                ),
                target_role="all",
                category="city",
                priority="critical",
                pinned=True,
                is_active=True,
                created_by=admin.user_id,
                created_at=_ago(hours=2),
                expires_at=_ahead(days=2),
            ),
            Notice(
                title="[배포] City Grid Coordinator v1.0 정식 운영 전환",
                body=(
                    "Phase 1~2 결정론적 검증을 통과한 City Grid Coordinator와 Building Battery Agent(17기), "
                    "CityLearn Constraint Guard가 정식 운영 단계로 전환되었습니다. 모든 충·방전 계획은 "
                    "Constraint Guard의 사전 검증(SOC 0.20~0.90, district score 개선)을 통과해야만 적용됩니다. "
                    "상세 운영 절차는 워크스페이스의 'City Power Grid' 토폴로지에서 확인하실 수 있습니다."
                ),
                target_role="all",
                category="city",
                priority="high",
                pinned=False,
                is_active=True,
                created_by=admin.user_id,
                created_at=_ago(days=1),
            ),
            Notice(
                title="[운영리포트] 6월 1주차 계통 운영 실적 — 피크 12.4% 절감",
                body=(
                    "지난주 도시 전력 그리드 운영 결과, 자동 피크 셰이빙을 통해 일 최대부하를 전주 대비 평균 12.4% "
                    "절감했습니다. 빌딩 평균 SOC는 0.58로 안정 구간을 유지했으며, 제약 위반(constraint violation)은 "
                    "0건이었습니다. 세부 지표는 운영 관리 > 운영 현황에서 확인 가능합니다."
                ),
                target_role="trust_ops",
                category="city",
                priority="normal",
                pinned=False,
                is_active=True,
                created_by=admin.user_id,
                created_at=_ago(days=2),
            ),
            # ── 회사 내부 공지 ──────────────────────────────────────────
            Notice(
                title="[거버넌스] AI 에이전트 인증(Certification) 의무화 정책 시행",
                body=(
                    "6월 10일부터 PUBLIC·DEPARTMENT 가시성으로 배포되는 모든 에이전트는 거버넌스팀의 인증을 "
                    "통과해야 합니다. 미인증 에이전트는 운영 단계(ACTIVE) 전환이 제한됩니다. 소유자께서는 신뢰 관리 > "
                    "인증 관리에서 인증을 신청하고, 적용 정책(데이터 보호·도구 사용 제한)을 연결해 주시기 바랍니다."
                ),
                target_role="all",
                category="governance",
                priority="high",
                pinned=True,
                is_active=True,
                created_by=admin.user_id,
                created_at=_ago(days=1, hours=4),
            ),
            Notice(
                title="[릴리스] 신뢰 관리 · 운영 관리 콘솔 정식 오픈",
                body=(
                    "MeshBoard에 신뢰 관리(Trust Workbench)와 운영 관리(Operations Console)가 추가되었습니다. "
                    "신뢰 관리에서는 정책·인증을 발급하고 에이전트에 연결할 수 있으며, 운영 관리에서는 전체 에이전트의 "
                    "상태(활성/일시중지/지원종료)를 한곳에서 관리하고 운영 지표를 확인할 수 있습니다. 좌측 사이드바에서 "
                    "이용해 보세요."
                ),
                target_role="all",
                category="release",
                priority="normal",
                pinned=False,
                is_active=True,
                created_by=admin.user_id,
                created_at=_ago(days=3),
            ),
            Notice(
                title="[시스템점검] 정기 점검 안내 — 금요일 자정 2시간",
                body=(
                    "이번 주 금요일 00:00~02:00, 데이터베이스 및 메시지 브로커 정기 점검이 예정되어 있습니다. "
                    "점검 시간 동안 에이전트 실행(invoke)과 실시간 메시징이 일시 중단됩니다. Trust Ops 팀은 점검 전 "
                    "진행 중인 작업을 안전 상태로 마무리하고 모니터링을 준비해 주십시오."
                ),
                target_role="trust_ops",
                category="system",
                priority="high",
                pinned=False,
                is_active=True,
                created_by=admin.user_id,
                created_at=_ago(days=2, hours=6),
                expires_at=_ahead(days=4),
            ),
            Notice(
                title="[보안] 보안 로그 모니터링 에이전트 권한 정기 점검 요청",
                body=(
                    "분기 보안 점검의 일환으로 PRIVATE 가시성 에이전트의 도구(MCP) 접근 권한을 재검토합니다. "
                    "특히 '보안 로그 모니터링' 에이전트의 외부 도구 연결 내역을 소유자께서 직접 확인하고, 불필요한 "
                    "권한은 신뢰 관리에서 정책으로 제한해 주시기 바랍니다. 점검 마감: 6월 14일."
                ),
                target_role="all",
                category="security",
                priority="critical",
                pinned=False,
                is_active=True,
                created_by=admin.user_id,
                created_at=_ago(days=1, hours=12),
                expires_at=_ahead(days=11),
            ),
            Notice(
                title="[교육] 사내 AI 에이전트 활용 온보딩 세션 안내",
                body=(
                    "MeshBoard를 처음 사용하는 구성원을 위한 온보딩 세션을 매주 화요일 오후 3시에 진행합니다. "
                    "에이전트 생성, 워크스페이스 협업, 신뢰·운영 관리 기본기를 다룹니다. 참가 신청은 사내 포털에서 "
                    "받습니다."
                ),
                target_role="all",
                category="general",
                priority="normal",
                pinned=False,
                is_active=True,
                created_by=admin.user_id,
                created_at=_ago(days=5),
            ),
            # ── 비활성(만료) 공지 — 필터링 동작 확인용 ───────────────────
            Notice(
                title="[종료] 5월 로그인 서버 지연 장애 사후 보고서",
                body="5월 발생한 로그인 서버 지연 문제에 대한 사후 분석(postmortem) 보고서가 공유되었습니다.",
                target_role="all",
                category="system",
                priority="normal",
                pinned=False,
                is_active=False,
                created_by=admin.user_id,
                created_at=_ago(days=20),
            ),
        ]

        db.add_all(notices)
        await db.commit()
        active = sum(1 for n in notices if n.is_active)
        print(f"✅ 공지 {len(notices)}건 적재 완료 (활성 {active}건).")


if __name__ == "__main__":
    asyncio.run(seed_notices())
