from typing import List

from pydantic import Field

from app.schemas.agent import AgentRead
from app.schemas.trust import TrustBadge


class MarketplaceAgentRead(AgentRead):
    certifications: List[TrustBadge] = Field(default_factory=list)
    trust_level: str = "unverified"
