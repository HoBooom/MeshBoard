import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.schemas.marketplace import MarketplaceAgentRead
from app.schemas.trust import TrustBadge


class MarketplaceSchemaTests(unittest.TestCase):
    def test_certified_agent_card_exposes_trust_badge(self):
        agent = SimpleNamespace(
            agent_id=uuid4(),
            owner_id=uuid4(),
            name="Verified Agent",
            version="1.0.0",
            purpose=None,
            description=None,
            approach=None,
            status="ACTIVE",
            visibility="PUBLIC",
            agent_card={},
            roles=[],
            collaborators=[],
            tools=[],
            metadata_={},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        badge = TrustBadge(id=uuid4(), name="안전성 인증", state="PASSED")
        card = MarketplaceAgentRead.model_validate(agent).model_copy(
            update={"certifications": [badge], "trust_level": "certified"}
        )
        self.assertEqual(card.trust_level, "certified")
        self.assertEqual(card.certifications[0].state, "PASSED")


if __name__ == "__main__":
    unittest.main()
