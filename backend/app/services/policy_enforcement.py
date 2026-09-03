"""Validation and runtime enforcement for active agent policies."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.certification import AgentCertification, Certification
from app.models.policy import AgentPolicy, Policy


SUPPORTED_POLICY_FIELDS = {
    "pii_masking": bool,
    "retention_days": int,
    "allowlist_only": bool,
    "audit_external_calls": bool,
    "rbac": bool,
    "scope": str,
    "soc_min": (int, float),
    "soc_max": (int, float),
    "require_validation": bool,
    "log_calls": bool,
    "blocked_terms": list,
    "max_input_chars": int,
    "allowed_tools": list,
    "denied_tools": list,
    "required_certifications": list,
}

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)")


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    message: str
    effective_tool_ids: frozenset[str]
    violations: tuple[str, ...]
    applied_policy_ids: tuple[str, ...]
    pii_redacted: bool = False


def validate_policy_template(template: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    unknown = sorted(set(template) - set(SUPPORTED_POLICY_FIELDS))
    if unknown:
        errors.append(f"지원하지 않는 정책 필드: {', '.join(unknown)}")
    for key, value in template.items():
        expected = SUPPORTED_POLICY_FIELDS.get(key)
        valid_type = isinstance(value, expected) if expected is not None else True
        # bool subclasses int in Python, but JSON policy numeric fields must not
        # silently accept true/false as 1/0.
        if expected is int and type(value) is not int:
            valid_type = False
        if expected == (int, float) and type(value) not in {int, float}:
            valid_type = False
        if not valid_type:
            errors.append(f"{key} 필드의 타입이 올바르지 않습니다.")
    for key in ("blocked_terms", "allowed_tools", "denied_tools", "required_certifications"):
        value = template.get(key)
        if isinstance(value, list) and not all(isinstance(item, str) and item.strip() for item in value):
            errors.append(f"{key} 필드는 비어 있지 않은 문자열 배열이어야 합니다.")
    if isinstance(template.get("retention_days"), int) and template["retention_days"] < 1:
        errors.append("retention_days는 1 이상이어야 합니다.")
    if isinstance(template.get("max_input_chars"), int) and template["max_input_chars"] < 1:
        errors.append("max_input_chars는 1 이상이어야 합니다.")
    soc_min, soc_max = template.get("soc_min"), template.get("soc_max")
    if isinstance(soc_min, (int, float)) and isinstance(soc_max, (int, float)) and soc_min >= soc_max:
        errors.append("soc_min은 soc_max보다 작아야 합니다.")
    return errors


def evaluate_policy_templates(
    *,
    message: str,
    agent_tools: Iterable[str],
    policies: Iterable[tuple[UUID | str, dict[str, Any]]],
    passed_certifications: Iterable[str] = (),
) -> PolicyDecision:
    effective_tools = set(agent_tools)
    violations: list[str] = []
    applied: list[str] = []
    sanitized = message
    redact_pii = False
    certificate_names = set(passed_certifications)

    for policy_id, template in policies:
        applied.append(str(policy_id))
        errors = validate_policy_template(template)
        if errors:
            violations.append(f"invalid active policy {policy_id}: {'; '.join(errors)}")
            continue
        max_chars = template.get("max_input_chars")
        if isinstance(max_chars, int) and len(message) > max_chars:
            violations.append(f"입력 길이가 정책 상한({max_chars}자)을 초과했습니다.")
        lowered = message.casefold()
        for term in template.get("blocked_terms") or []:
            if term.casefold() in lowered:
                violations.append(f"차단어 정책에 의해 입력이 거부되었습니다: {term}")
        required = set(template.get("required_certifications") or [])
        missing = sorted(required - certificate_names)
        if missing:
            violations.append(f"필수 인증이 없습니다: {', '.join(missing)}")
        allowed_tools = template.get("allowed_tools")
        if allowed_tools is not None:
            effective_tools.intersection_update(allowed_tools)
        effective_tools.difference_update(template.get("denied_tools") or [])
        redact_pii = redact_pii or bool(template.get("pii_masking"))

    if redact_pii:
        sanitized = _EMAIL_RE.sub("[EMAIL]", sanitized)
        sanitized = _PHONE_RE.sub("[PHONE]", sanitized)
    return PolicyDecision(
        allowed=not violations,
        message=sanitized,
        effective_tool_ids=frozenset(effective_tools),
        violations=tuple(violations),
        applied_policy_ids=tuple(applied),
        pii_redacted=sanitized != message,
    )


async def resolve_agent_policy(
    db: AsyncSession, agent: Agent, message: str
) -> PolicyDecision:
    policy_rows = (
        await db.execute(
            select(Policy.policy_id, Policy.template)
            .join(AgentPolicy, AgentPolicy.policy_id == Policy.policy_id)
            .where(AgentPolicy.agent_id == agent.agent_id, Policy.status == "ACTIVE")
        )
    ).all()
    now = datetime.now(timezone.utc)
    passed_certifications = (
        await db.execute(
            select(Certification.name)
            .join(
                AgentCertification,
                AgentCertification.certification_id == Certification.certification_id,
            )
            .where(
                AgentCertification.agent_id == agent.agent_id,
                Certification.state == "PASSED",
                or_(Certification.expires_at.is_(None), Certification.expires_at > now),
            )
        )
    ).scalars().all()
    return evaluate_policy_templates(
        message=message,
        agent_tools=agent.tools or [],
        policies=policy_rows,
        passed_certifications=passed_certifications,
    )
