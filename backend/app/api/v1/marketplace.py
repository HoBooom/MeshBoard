from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.agent import Agent
from app.schemas.agent import AgentRead
from app.schemas.auth import UserResponse
from app.core.security import get_current_user

router = APIRouter(prefix="/marketplace", tags=["marketplace"])

@router.get("/agents", response_model=List[AgentRead])
async def get_marketplace_agents(
    q: Optional[str] = Query(None, description="검색어 (이름, 설명, 목적)"),
    category: Optional[str] = Query(None, description="카테고리 필터"),
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    마켓플레이스 에이전트 목록을 조회합니다.
    - 일반 텍스트 검색 (q) 및 카테고리 필터링 지원.
    - PUBLIC 에이전트 및 자신이 소유한 에이전트만 반환합니다.
    """
    stmt = select(Agent).where(Agent.status == "ACTIVE")
    
    # 가시성 필터: PUBLIC이거나 내가 소유자이거나
    stmt = stmt.where(
        or_(
            Agent.visibility == "PUBLIC",
            Agent.owner_id == current_user.user_id
        )
    )
    
    # 텍스트 검색 (키워드)
    if q:
        search_term = f"%{q}%"
        stmt = stmt.where(
            or_(
                Agent.name.ilike(search_term),
                Agent.description.ilike(search_term),
                Agent.purpose.ilike(search_term)
            )
        )
        
    # 카테고리 필터 (JSONB 내부 필드 검색)
    if category:
        # metadata_ 내부의 'category' 속성이 주어진 category와 일치하는지 확인
        stmt = stmt.where(Agent.metadata_["category"].astext == category)
        
    stmt = stmt.order_by(Agent.created_at.desc())
    
    result = await db.execute(stmt)
    agents = result.scalars().all()
    
    return agents
