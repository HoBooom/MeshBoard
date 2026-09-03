import unittest
from uuid import uuid4

from app.services.message_broker import _explicit_agent_targets


class MessageTargetingTests(unittest.TestCase):
    def test_explicit_ids_and_roles_select_only_placed_agents_in_order(self):
        hr_agent = uuid4()
        finance_agent = uuid4()
        unplaced_agent = uuid4()

        selected = _explicit_agent_targets(
            [hr_agent, finance_agent],
            {hr_agent: ["HR"], finance_agent: ["finance", "reviewer"]},
            [unplaced_agent, hr_agent],
            ["REVIEWER"],
        )

        self.assertEqual(selected, [hr_agent, finance_agent])

    def test_empty_explicit_selectors_match_nothing(self):
        agent_id = uuid4()
        self.assertEqual(
            _explicit_agent_targets([agent_id], {agent_id: ["ops"]}, [], []),
            [],
        )
