"""Pure, deterministic Agent Mesh routing used by isolated sandbox runs."""

from __future__ import annotations

import re
from collections import deque
from typing import Any, Iterable

from app.services.subscription_rules import (
    SubscriptionEvent,
    SubscriptionRule,
    evaluate_subscription,
)


MENTION_RE = re.compile(r"(?<!\S)@([^\s@]+)")


def _key(value: str) -> str:
    return re.sub(r"\s+", "_", value.strip()).lower()


def _rule_matches(event: dict[str, Any], rule: dict[str, Any] | None) -> tuple[bool, str]:
    """구독 규칙 평가를 브로커와 공유되는 단일 구현에 위임합니다.

    Sandbox 에는 워크스페이스 edge 가 없어 규칙 자체가 구독이므로, 규칙이 없으면 매칭되지 않는다.
    """
    decision = evaluate_subscription(
        SubscriptionEvent.from_mapping(event),
        SubscriptionRule.from_mapping(rule) if rule else None,
        missing_rule_matches=False,
    )
    return decision.matched, decision.reason


def simulate_sandbox_event(
    event: dict[str, Any], agent_snapshots: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """Return routing and handoff decisions without invoking tools or writing operational rows."""

    agents = list(agent_snapshots)
    by_id = {str(agent["agent_id"]): agent for agent in agents}
    by_name = {_key(str(agent["name"])): agent for agent in agents}
    mentions = {_key(match.group(1)) for match in MENTION_RE.finditer(str(event.get("message") or ""))}

    initial: list[tuple[dict[str, Any], str]] = []
    decisions: list[dict[str, Any]] = []
    for agent in agents:
        if agent.get("status") != "ACTIVE":
            decisions.append(
                {
                    "agent_id": str(agent["agent_id"]),
                    "agent_name": agent["name"],
                    "action": "skip",
                    "reason": f"agent status is {agent.get('status')}",
                    "status": "SKIPPED",
                }
            )
            continue
        if mentions:
            if _key(str(agent["name"])) in mentions:
                initial.append((agent, "matched direct @mention"))
            else:
                decisions.append(
                    {
                        "agent_id": str(agent["agent_id"]),
                        "agent_name": agent["name"],
                        "action": "skip",
                        "reason": "another agent was directly mentioned",
                        "status": "SKIPPED",
                    }
                )
            continue
        matched, reason = _rule_matches(event, agent.get("subscription_rule"))
        if matched:
            initial.append((agent, reason))
        else:
            decisions.append(
                {
                    "agent_id": str(agent["agent_id"]),
                    "agent_name": agent["name"],
                    "action": "skip",
                    "reason": reason,
                    "status": "SKIPPED",
                }
            )

    queue = deque(initial)
    routed: list[str] = []
    routed_set: set[str] = set()
    while queue:
        agent, reason = queue.popleft()
        agent_id = str(agent["agent_id"])
        if agent_id in routed_set:
            continue
        routed_set.add(agent_id)
        routed.append(agent_id)
        decisions.append(
            {
                "agent_id": str(agent["agent_id"]),
                "agent_name": agent["name"],
                "action": "consume" if reason.startswith("matched") else "handoff",
                "reason": reason,
                "status": "SIMULATED",
            }
        )
        for collaborator in agent.get("collaborators") or []:
            target = by_id.get(str(collaborator)) or by_name.get(_key(str(collaborator)))
            if target and target.get("status") == "ACTIVE" and str(target["agent_id"]) not in routed_set:
                queue.append((target, f"handoff from {agent['name']}"))

    for sequence, decision in enumerate(decisions, start=1):
        decision["sequence"] = sequence
    return {"routed_agent_ids": routed, "decision_log": decisions}
