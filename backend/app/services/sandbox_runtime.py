"""Pure, deterministic Agent Mesh routing used by isolated sandbox runs."""

from __future__ import annotations

import re
from collections import deque
from typing import Any, Iterable


PRIORITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
MENTION_RE = re.compile(r"(?<!\S)@([^\s@]+)")


def _key(value: str) -> str:
    return re.sub(r"\s+", "_", value.strip()).lower()


def _rule_matches(event: dict[str, Any], rule: dict[str, Any] | None) -> tuple[bool, str]:
    if not rule or not rule.get("is_active", True):
        return False, "subscription rule is inactive"

    event_tags = set(event.get("tags") or [])
    ignored_tags = set(rule.get("ignore_tags") or [])
    if event_tags.intersection(ignored_tags):
        return False, "event contains an ignored tag"

    minimum = PRIORITY_ORDER.get(str(rule.get("min_priority") or "medium"), 1)
    actual = PRIORITY_ORDER.get(str(event.get("priority") or "medium"), 1)
    if actual < minimum:
        return False, "event priority is below the subscription threshold"

    filters = (
        ("domain", "watch_domains"),
        ("intent", "watch_intents"),
    )
    for event_key, rule_key in filters:
        watched = set(rule.get(rule_key) or [])
        if watched and event.get(event_key) not in watched:
            return False, f"{event_key} does not match the subscription"

    watched_tags = set(rule.get("watch_tags") or [])
    if watched_tags and not event_tags.intersection(watched_tags):
        return False, "event tags do not match the subscription"
    return True, "matched active subscription rule"


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
