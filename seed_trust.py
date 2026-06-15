"""MeshBoard — 신뢰 관리 시드 데이터.

회사 내부 거버넌스 운영을 가정한 정책(Policy)·인증(Certification)을 생성하고
일부 에이전트에 연결하여 신뢰 현황 화면을 채운다.

멱등 실행: 기존 연결/정책/인증을 모두 제거한 뒤 재적재한다.
실행: cd backend && uv run python ../seed_trust.py
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.db.session import async_session_factory
from app.models.agent import Agent
from app.models.certification import AgentCertification, Certification
from app.models.policy import AgentPolicy, Policy
from app.models.user import User


def _ahead(days: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


async def seed_trust() -> None:
    async with async_session_factory() as db:
        admin = (
            await db.execute(select(User).where(User.email == "admin@meshboard.io"))
        ).scalars().first()
        if not admin:
            print("❌ admin@meshboard.io 사용자를 찾을 수 없습니다.")
            return

        # 멱등성: 연결 → 정책/인증 순으로 초기화
        await db.execute(delete(AgentPolicy))
        await db.execute(delete(AgentCertification))
        await db.execute(delete(Policy))
        await db.execute(delete(Certification))
        await db.commit()

        # ── 정책 ──────────────────────────────────────────────
        policies = {
            "data_protection": Policy(
                name="데이터 보호 정책",
                purpose="개인정보 및 민감정보 처리 통제",
                description="에이전트가 처리하는 데이터의 수집·보관·파기 규칙과 마스킹 요건을 정의합니다.",
                template={"pii_masking": True, "retention_days": 90},
                status="ACTIVE",
                created_by=admin.user_id,
            ),
            "tool_restriction": Policy(
                name="도구(MCP) 사용 제한 정책",
                purpose="외부 도구 호출 범위 통제",
                description="승인된 MCP 도구만 사용하도록 제한하고, 외부 네트워크 호출을 감사합니다.",
                template={"allowlist_only": True, "audit_external_calls": True},
                status="ACTIVE",
                created_by=admin.user_id,
            ),
            "hr_access": Policy(
                name="인사정보 접근 통제 정책",
                purpose="HR 데이터 최소권한 접근",
                description="인사·근태 데이터에 대한 역할 기반 최소권한 접근을 강제합니다.",
                template={"rbac": True, "scope": "hr"},
                status="ACTIVE",
                created_by=admin.user_id,
            ),
            "grid_safety": Policy(
                name="도시 그리드 안전 제약 정책",
                purpose="전력 계통 안전 한계 준수",
                description="배터리 SOC 0.20~0.90 범위, district score 개선 검증 통과를 의무화합니다.",
                template={"soc_min": 0.2, "soc_max": 0.9, "require_validation": True},
                status="ACTIVE",
                created_by=admin.user_id,
            ),
            "external_audit": Policy(
                name="외부 API 호출 감사 정책",
                purpose="외부 연동 추적성 확보",
                description="외부 API 호출 로그를 보존하고 이상 패턴을 탐지합니다. (검토 중)",
                template={"log_calls": True},
                status="DRAFT",
                created_by=admin.user_id,
            ),
        }

        # ── 인증 ──────────────────────────────────────────────
        certs = {
            "safety": Certification(
                name="기본 안전성 인증",
                certifier_id=admin.user_id,
                state="PASSED",
                notes="프롬프트 인젝션·탈옥 저항성 기본 테스트 통과",
                issued_at=datetime.now(timezone.utc),
                expires_at=_ahead(365),
            ),
            "data_gov": Certification(
                name="데이터 거버넌스 인증",
                certifier_id=admin.user_id,
                state="PASSED",
                notes="개인정보 처리방침 및 마스킹 요건 충족",
                issued_at=datetime.now(timezone.utc),
                expires_at=_ahead(365),
            ),
            "grid_ops": Certification(
                name="도시 그리드 운영 인증",
                certifier_id=admin.user_id,
                state="PASSED",
                notes="CityLearn 결정론적 검증 통과, 제약 위반 0건",
                issued_at=datetime.now(timezone.utc),
                expires_at=_ahead(180),
            ),
            "security_review": Certification(
                name="분기 보안 심사",
                certifier_id=admin.user_id,
                state="PENDING",
                notes="도구 권한 재검토 진행 중",
            ),
            "ethics": Certification(
                name="윤리 영향 검토",
                certifier_id=admin.user_id,
                state="PENDING",
                notes="고위험 의사결정 자동화 영향 평가 대기",
            ),
        }

        db.add_all(list(policies.values()))
        db.add_all(list(certs.values()))
        await db.flush()

        # ── 에이전트 연결 ──────────────────────────────────────
        agents = (await db.execute(select(Agent))).scalars().all()
        by_name = {a.name: a for a in agents}

        def link_policy(agent_name: str, key: str) -> None:
            agent = by_name.get(agent_name)
            if agent:
                db.add(
                    AgentPolicy(
                        agent_id=agent.agent_id,
                        policy_id=policies[key].policy_id,
                        applied_by=admin.user_id,
                    )
                )

        def link_cert(agent_name: str, key: str) -> None:
            agent = by_name.get(agent_name)
            if agent:
                db.add(
                    AgentCertification(
                        agent_id=agent.agent_id,
                        certification_id=certs[key].certification_id,
                    )
                )

        # certified 에이전트들
        link_policy("인사 및 근태 관리 봇", "hr_access")
        link_policy("인사 및 근태 관리 봇", "data_protection")
        link_cert("인사 및 근태 관리 봇", "data_gov")

        link_policy("IT 지원 데스크", "tool_restriction")
        link_cert("IT 지원 데스크", "safety")

        link_policy("도시 전력 관리", "grid_safety")
        link_cert("도시 전력 관리", "grid_ops")

        link_policy("재무/비용 청구 검토 봇", "data_protection")
        link_cert("재무/비용 청구 검토 봇", "safety")

        # partial (정책/대기 인증만)
        link_policy("City Grid Coordinator", "grid_safety")
        link_cert("보안 로그 모니터링", "security_review")
        link_cert("영업 데이터 분석가", "ethics")

        await db.commit()
        print(
            f"✅ 정책 {len(policies)}건, 인증 {len(certs)}건 적재 및 에이전트 연결 완료."
        )


if __name__ == "__main__":
    asyncio.run(seed_trust())
