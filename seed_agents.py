import asyncio
import uuid
import sys
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.config import settings
from app.db.session import async_session_factory
from app.models.agent import Agent
from app.models.user import User

async def seed_agents():
    # 1. 관리자 사용자(admin@meshboard.io) 찾기
    async with async_session_factory() as session:
        from sqlalchemy import select
        result = await session.execute(select(User).where(User.email == "admin@meshboard.io"))
        admin_user = result.scalars().first()
        
        if not admin_user:
            print("❌ admin@meshboard.io 사용자를 찾을 수 없습니다.")
            sys.exit(1)
            
        owner_id = admin_user.user_id
        
        # 2. 더미 에이전트 목록 정의
        dummy_agents = [
            {
                "name": "인사 및 근태 관리 봇",
                "version": "1.0.0",
                "purpose": "직원들의 연차, 근태, 부서 정보를 관리하고 관련 질문에 답변합니다.",
                "description": "사내 HR 시스템(Workday 등)과 연동되어 직원의 연차 잔여일 조회, 휴가 신청, 급여 명세서 확인 등을 도와주는 에이전트입니다. 보안을 위해 각 직원의 정보만 접근할 수 있도록 설계되었습니다.",
                "approach": "API Integration with HR system",
                "status": "ACTIVE",
                "visibility": "PUBLIC",
                "metadata_": {"category": "HR"},
                "roles": ["hr_manager"],
                "tools": ["check_leave_balance", "submit_leave_request"]
            },
            {
                "name": "IT 지원 데스크",
                "version": "2.1.0",
                "purpose": "사내 IT 관련 문제를 접수하고 1차적인 트러블슈팅 가이드를 제공합니다.",
                "description": "네트워크 연결, 소프트웨어 설치 권한, 패스워드 리셋 등의 일반적인 IT 문의를 자동으로 처리하는 헬프데스크 봇입니다. 복잡한 문제는 실제 IT 부서 담당자에게 티켓을 생성해 이관합니다.",
                "approach": "RAG based on IT Confluence + Ticketing API",
                "status": "ACTIVE",
                "visibility": "PUBLIC",
                "metadata_": {"category": "IT"},
                "roles": ["it_support"],
                "tools": ["create_jira_ticket", "search_confluence"]
            },
            {
                "name": "영업 데이터 분석가",
                "version": "1.5.0",
                "purpose": "CRM 데이터를 분석하여 리드(Lead) 예측 및 파이프라인 관리를 돕습니다.",
                "description": "Salesforce에 연동되어 이번 분기 매출 예측, 담당자별 성과 조회, 이탈 예상 고객 알림 등을 제공합니다. 영업 부서 내에서만 열람 가능합니다.",
                "approach": "Data Analysis & ML Prediction",
                "status": "ACTIVE",
                "visibility": "DEPARTMENT",
                "metadata_": {"category": "Sales"},
                "roles": ["sales_rep", "sales_manager"],
                "tools": ["query_crm", "generate_forecast"]
            },
            {
                "name": "보안 로그 모니터링",
                "version": "3.0.0",
                "purpose": "시스템 접근 로그를 분석하여 이상 행동을 탐지합니다.",
                "description": "서버 및 애플리케이션 접속 로그를 실시간으로 스트리밍 받아 분석하며, 비정상적인 IP 접근이나 대량의 데이터 다운로드가 감지되면 즉각 경고를 발생시킵니다.",
                "approach": "Anomaly Detection AI",
                "status": "ACTIVE",
                "visibility": "PRIVATE",
                "metadata_": {"category": "Security"},
                "roles": ["security_admin"],
                "tools": ["search_logs", "block_ip"]
            },
            {
                "name": "재무/비용 청구 검토 봇",
                "version": "1.2.0",
                "purpose": "임직원이 올린 법인카드 및 비용 청구 내역을 정책에 맞게 1차 검수합니다.",
                "description": "영수증 OCR 데이터를 바탕으로 사내 비용 정책(식대 한도, 유흥업소 결제 여부 등)을 확인하고, 문제가 없으면 재무팀에 승인 요청을 넘깁니다.",
                "approach": "OCR + Rules + LLM Assessment",
                "status": "ACTIVE",
                "visibility": "PUBLIC",
                "metadata_": {"category": "Finance"},
                "roles": ["employee", "finance_manager"],
                "tools": ["extract_receipt_info", "check_expense_policy"]
            }
        ]
        
        # 3. 기존 에이전트 초기화 (옵션)
        # await session.execute(Agent.__table__.delete())
        
        # 4. 데이터 삽입
        inserted_count = 0
        for agent_data in dummy_agents:
            # 중복 체크
            stmt = select(Agent).where(Agent.name == agent_data["name"])
            existing = await session.execute(stmt)
            if existing.scalars().first():
                continue
                
            agent = Agent(
                owner_id=owner_id,
                name=agent_data["name"],
                version=agent_data["version"],
                purpose=agent_data["purpose"],
                description=agent_data["description"],
                approach=agent_data["approach"],
                status=agent_data["status"],
                visibility=agent_data["visibility"],
                metadata_=agent_data["metadata_"],
                roles=agent_data["roles"],
                tools=agent_data["tools"],
                agent_card={}
            )
            session.add(agent)
            inserted_count += 1
            
        await session.commit()
        print(f"✅ {inserted_count}개의 더미 에이전트가 성공적으로 삽입되었습니다!")

if __name__ == "__main__":
    asyncio.run(seed_agents())
