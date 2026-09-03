"""에이전트 구독 규칙(`agent_subscription_rules`)의 단일 평가 구현.

예전에는 이 규칙을 **Sandbox 시뮬레이터만** 해석하고 프로덕션 브로커는 무시했다.
그래서 "Sandbox 가 운영과 같은 라우팅 결정을 재현한다"는 설명이 실제로는 성립하지 않았다.
두 경로가 같은 함수를 쓰도록 여기로 모은다.

두 경로의 차이는 **규칙이 없을 때의 기본값** 하나뿐이며, 그 차이는 의도된 것이다.

- Sandbox: 그래프(edge)가 없으므로 규칙 자체가 구독이다 → 규칙이 없으면 매칭되지 않는다.
- 브로커: 구독은 워크스페이스 edge 로 표현되고 규칙은 그 위의 내용 필터다
  → 규칙이 없으면 edge 만으로 수신한다.

`@mention` 과 명시적 target 은 직접 지정이므로 이 필터를 거치지 않는다. 사람이 특정 에이전트를
콕 집어 부른 요청까지 내용 필터로 막으면 놀라운 동작이 된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

PRIORITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass(frozen=True)
class SubscriptionEvent:
    """규칙 평가에 필요한 메시지 속성만 담은 값 객체."""

    domain: Optional[str] = None
    intent: Optional[str] = None
    priority: Optional[str] = None
    tags: tuple[str, ...] = ()
    sender_id: Optional[str] = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "SubscriptionEvent":
        sender = data.get("sender_id")
        return cls(
            domain=data.get("domain"),
            intent=data.get("intent"),
            priority=data.get("priority"),
            tags=tuple(data.get("tags") or ()),
            sender_id=str(sender) if sender is not None else None,
        )


@dataclass(frozen=True)
class SubscriptionDecision:
    matched: bool
    reason: str


@dataclass(frozen=True)
class SubscriptionRule:
    """규칙의 정규화된 형태. ORM 행과 dict 스냅샷 양쪽에서 만들 수 있다."""

    is_active: bool = True
    watch_domains: tuple[str, ...] = ()
    watch_intents: tuple[str, ...] = ()
    watch_tags: tuple[str, ...] = ()
    watch_senders: tuple[str, ...] = ()
    ignore_tags: tuple[str, ...] = ()
    ignore_senders: tuple[str, ...] = ()
    min_priority: str = "medium"

    @staticmethod
    def _texts(values: Optional[Iterable[Any]]) -> tuple[str, ...]:
        return tuple(str(value) for value in (values or ()))

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "SubscriptionRule":
        return cls(
            is_active=bool(data.get("is_active", True)),
            watch_domains=cls._texts(data.get("watch_domains")),
            watch_intents=cls._texts(data.get("watch_intents")),
            watch_tags=cls._texts(data.get("watch_tags")),
            watch_senders=cls._texts(data.get("watch_senders")),
            ignore_tags=cls._texts(data.get("ignore_tags")),
            ignore_senders=cls._texts(data.get("ignore_senders")),
            min_priority=str(data.get("min_priority") or "medium"),
        )

    @classmethod
    def from_model(cls, rule: Any) -> "SubscriptionRule":
        return cls(
            is_active=bool(getattr(rule, "is_active", True)),
            watch_domains=cls._texts(getattr(rule, "watch_domains", ())),
            watch_intents=cls._texts(getattr(rule, "watch_intents", ())),
            watch_tags=cls._texts(getattr(rule, "watch_tags", ())),
            watch_senders=cls._texts(getattr(rule, "watch_senders", ())),
            ignore_tags=cls._texts(getattr(rule, "ignore_tags", ())),
            ignore_senders=cls._texts(getattr(rule, "ignore_senders", ())),
            min_priority=str(getattr(rule, "min_priority", None) or "medium"),
        )


def evaluate_subscription(
    event: SubscriptionEvent,
    rule: Optional[SubscriptionRule],
    *,
    missing_rule_matches: bool,
) -> SubscriptionDecision:
    """이벤트가 구독 규칙을 통과하는지 판정합니다.

    `missing_rule_matches` 는 규칙이 아예 없을 때의 기본값이다 (모듈 docstring 참고).
    """
    if rule is None:
        return SubscriptionDecision(
            missing_rule_matches,
            "no subscription rule configured"
            if missing_rule_matches
            else "agent has no subscription rule",
        )
    if not rule.is_active:
        return SubscriptionDecision(False, "subscription rule is inactive")

    if event.sender_id and event.sender_id in rule.ignore_senders:
        return SubscriptionDecision(False, "sender is on the ignore list")

    event_tags = set(event.tags)
    if event_tags.intersection(rule.ignore_tags):
        return SubscriptionDecision(False, "event contains an ignored tag")

    minimum = PRIORITY_ORDER.get(rule.min_priority, 1)
    actual = PRIORITY_ORDER.get(str(event.priority or "medium"), 1)
    if actual < minimum:
        return SubscriptionDecision(False, "event priority is below the subscription threshold")

    for label, value, watched in (
        ("domain", event.domain, rule.watch_domains),
        ("intent", event.intent, rule.watch_intents),
    ):
        if watched and value not in set(watched):
            return SubscriptionDecision(False, f"{label} does not match the subscription")

    if rule.watch_tags and not event_tags.intersection(rule.watch_tags):
        return SubscriptionDecision(False, "event tags do not match the subscription")

    if rule.watch_senders and (
        event.sender_id is None or event.sender_id not in set(rule.watch_senders)
    ):
        return SubscriptionDecision(False, "sender is not on the watch list")

    return SubscriptionDecision(True, "matched active subscription rule")
