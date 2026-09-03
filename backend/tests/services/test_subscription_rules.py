"""구독 규칙 평가의 공유 구현 테스트.

이 함수는 프로덕션 브로커와 Sandbox 시뮬레이터가 **함께** 쓴다. 두 경로가 서로 다른 판정을
내리지 않도록 여기서 의미를 고정한다.
"""

from __future__ import annotations

import unittest

from app.services.subscription_rules import (
    SubscriptionEvent,
    SubscriptionRule,
    evaluate_subscription,
)


def _event(**overrides) -> SubscriptionEvent:
    base = {"domain": "ops", "intent": "request", "priority": "medium", "tags": ()}
    base.update(overrides)
    return SubscriptionEvent(**base)


class MissingRuleDefaultTests(unittest.TestCase):
    """규칙이 없을 때의 기본값만 두 경로가 다르다 — 그 차이를 명시적으로 고정한다."""

    def test_broker_receives_when_no_rule_is_configured(self) -> None:
        decision = evaluate_subscription(_event(), None, missing_rule_matches=True)
        self.assertTrue(decision.matched)

    def test_sandbox_does_not_match_when_no_rule_is_configured(self) -> None:
        decision = evaluate_subscription(_event(), None, missing_rule_matches=False)
        self.assertFalse(decision.matched)


class RuleFilterTests(unittest.TestCase):
    def test_inactive_rule_never_matches(self) -> None:
        rule = SubscriptionRule(is_active=False)
        self.assertFalse(evaluate_subscription(_event(), rule, missing_rule_matches=True).matched)

    def test_empty_rule_matches_everything(self) -> None:
        self.assertTrue(
            evaluate_subscription(_event(), SubscriptionRule(), missing_rule_matches=True).matched
        )

    def test_domain_outside_the_watch_list_is_filtered(self) -> None:
        rule = SubscriptionRule(watch_domains=("finance",))
        self.assertFalse(
            evaluate_subscription(_event(domain="ops"), rule, missing_rule_matches=True).matched
        )
        self.assertTrue(
            evaluate_subscription(_event(domain="finance"), rule, missing_rule_matches=True).matched
        )

    def test_intent_outside_the_watch_list_is_filtered(self) -> None:
        rule = SubscriptionRule(watch_intents=("incident",))
        self.assertFalse(
            evaluate_subscription(_event(intent="request"), rule, missing_rule_matches=True).matched
        )

    def test_priority_below_the_threshold_is_filtered(self) -> None:
        rule = SubscriptionRule(min_priority="high")
        self.assertFalse(
            evaluate_subscription(_event(priority="medium"), rule, missing_rule_matches=True).matched
        )
        self.assertTrue(
            evaluate_subscription(_event(priority="critical"), rule, missing_rule_matches=True).matched
        )

    def test_ignored_tag_wins_over_a_watched_tag(self) -> None:
        rule = SubscriptionRule(watch_tags=("deploy",), ignore_tags=("noise",))
        decision = evaluate_subscription(
            _event(tags=("deploy", "noise")), rule, missing_rule_matches=True
        )
        self.assertFalse(decision.matched)
        self.assertIn("ignored tag", decision.reason)

    def test_watch_tags_requires_at_least_one_overlap(self) -> None:
        rule = SubscriptionRule(watch_tags=("deploy",))
        self.assertFalse(
            evaluate_subscription(_event(tags=("other",)), rule, missing_rule_matches=True).matched
        )
        self.assertTrue(
            evaluate_subscription(_event(tags=("deploy",)), rule, missing_rule_matches=True).matched
        )

    def test_ignored_sender_is_filtered(self) -> None:
        rule = SubscriptionRule(ignore_senders=("sender-1",))
        self.assertFalse(
            evaluate_subscription(
                _event(sender_id="sender-1"), rule, missing_rule_matches=True
            ).matched
        )

    def test_watch_senders_excludes_everyone_else(self) -> None:
        rule = SubscriptionRule(watch_senders=("sender-1",))
        self.assertTrue(
            evaluate_subscription(
                _event(sender_id="sender-1"), rule, missing_rule_matches=True
            ).matched
        )
        self.assertFalse(
            evaluate_subscription(
                _event(sender_id="sender-2"), rule, missing_rule_matches=True
            ).matched
        )


class RuleConstructionTests(unittest.TestCase):
    def test_orm_row_and_dict_snapshot_produce_the_same_rule(self) -> None:
        payload = {
            "is_active": True,
            "watch_domains": ["ops"],
            "watch_intents": [],
            "watch_tags": ["deploy"],
            "watch_senders": [],
            "ignore_tags": ["noise"],
            "ignore_senders": [],
            "min_priority": "high",
        }

        class _Row:
            pass

        row = _Row()
        for key, value in payload.items():
            setattr(row, key, value)

        self.assertEqual(SubscriptionRule.from_mapping(payload), SubscriptionRule.from_model(row))


if __name__ == "__main__":
    unittest.main()
