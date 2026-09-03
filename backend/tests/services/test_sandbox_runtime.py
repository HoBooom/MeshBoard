import unittest
from uuid import uuid4

from app.services.sandbox_runtime import simulate_sandbox_event


class SandboxRuntimeTests(unittest.TestCase):
    def test_subscription_match_and_collaborator_handoff(self):
        first_id, second_id = uuid4(), uuid4()
        result = simulate_sandbox_event(
            {
                "domain": "security",
                "intent": "incident",
                "message": "의심 트래픽을 조사해 주세요",
                "priority": "critical",
                "tags": ["alert"],
            },
            [
                {
                    "agent_id": first_id,
                    "name": "탐지 에이전트",
                    "status": "ACTIVE",
                    "collaborators": [str(second_id)],
                    "subscription_rule": {
                        "watch_domains": ["security"],
                        "watch_intents": [],
                        "watch_tags": ["alert"],
                        "ignore_tags": [],
                        "min_priority": "high",
                        "is_active": True,
                    },
                },
                {
                    "agent_id": second_id,
                    "name": "대응 에이전트",
                    "status": "ACTIVE",
                    "collaborators": [],
                    "subscription_rule": None,
                },
            ],
        )
        self.assertEqual(result["routed_agent_ids"], [str(first_id), str(second_id)])
        self.assertEqual(result["decision_log"][-1]["action"], "handoff")

    def test_direct_mention_overrides_subscription_and_suspended_agents_are_skipped(self):
        selected_id, suspended_id = uuid4(), uuid4()
        result = simulate_sandbox_event(
            {
                "domain": "hr",
                "intent": "question",
                "message": "@선택_에이전트 확인해 주세요",
                "priority": "low",
                "tags": [],
            },
            [
                {
                    "agent_id": selected_id,
                    "name": "선택 에이전트",
                    "status": "ACTIVE",
                    "collaborators": [],
                    "subscription_rule": None,
                },
                {
                    "agent_id": suspended_id,
                    "name": "중지 에이전트",
                    "status": "SUSPENDED",
                    "collaborators": [],
                    "subscription_rule": None,
                },
            ],
        )
        self.assertEqual(result["routed_agent_ids"], [str(selected_id)])
        suspended = next(
            row for row in result["decision_log"] if row["agent_id"] == str(suspended_id)
        )
        self.assertEqual(suspended["status"], "SKIPPED")

    def test_run_is_pure_and_does_not_mutate_inputs(self):
        event = {"domain": "ops", "intent": "check", "message": "test", "tags": []}
        agents = []
        result = simulate_sandbox_event(event, agents)
        self.assertEqual(result, {"routed_agent_ids": [], "decision_log": []})
        self.assertNotIn("production_write_count", event)


if __name__ == "__main__":
    unittest.main()
