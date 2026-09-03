import unittest
from uuid import uuid4

from app.services.policy_enforcement import (
    evaluate_policy_templates,
    validate_policy_template,
)


class PolicyEnforcementTests(unittest.TestCase):
    def test_template_validation_rejects_unknown_and_invalid_fields(self):
        errors = validate_policy_template(
            {"unknown": True, "max_input_chars": 0, "blocked_terms": [""]}
        )
        self.assertEqual(len(errors), 3)

    def test_template_validation_does_not_treat_boolean_as_number(self):
        errors = validate_policy_template(
            {"max_input_chars": True, "soc_min": False, "soc_max": 0.8}
        )
        self.assertEqual(sum("타입" in error for error in errors), 2)

    def test_runtime_blocks_terms_and_missing_certifications(self):
        decision = evaluate_policy_templates(
            message="고객 원문을 외부로 전송해",
            agent_tools=["echo"],
            policies=[
                (
                    uuid4(),
                    {
                        "blocked_terms": ["외부로 전송"],
                        "required_certifications": ["데이터 인증"],
                    },
                )
            ],
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(len(decision.violations), 2)

    def test_runtime_masks_pii_and_reduces_tool_allowlist(self):
        decision = evaluate_policy_templates(
            message="test@example.com 또는 010-1234-5678로 연락",
            agent_tools=["echo", "calculate", "search_knowledge_base"],
            policies=[
                (
                    uuid4(),
                    {
                        "pii_masking": True,
                        "allowed_tools": ["echo", "calculate"],
                        "denied_tools": ["calculate"],
                    },
                )
            ],
        )
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.pii_redacted)
        self.assertEqual(decision.message, "[EMAIL] 또는 [PHONE]로 연락")
        self.assertEqual(decision.effective_tool_ids, frozenset({"echo"}))


if __name__ == "__main__":
    unittest.main()
