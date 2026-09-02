"""OpenSynCity(outage_mpc_mesh) 에이전트 발언을 로컬 Qwen으로 자연어 생성.

팀원들이 쓴 로컬 Qwen과 동일한 컨셉: 결정론적 모델(MASMPCAgent)이 만든 사실(행동·SoC·예측·정전
위험)을 그대로 유지하면서, 각 에이전트가 자기 역할 인격으로 1인칭 한국어 한 문장을 발화하도록
로컬 LLM(Ollama/vLLM/LM Studio의 OpenAI 호환 /v1)에 위임한다.

설계 원칙:
- **사실 불변**: 프롬프트에 결정론적 `reason`(수치 포함)을 ground-truth로 주고 "수치를 바꾸지 말라"고
  강제한다. LLM은 표현만 바꾼다(환각·수치 왜곡 방지).
- **전원 LLM**: step당 모든 에이전트(정전감지/요금·탄소 리드/건물 N)를 동시 호출(semaphore 상한).
- **견고성**: 비활성(MESH_LLM_NARRATION_ENABLED=false)이거나 호출 실패/타임아웃이면 템플릿 문장으로
  그대로 폴백 → Qwen이 없어도 board는 동작한다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from app.core.config import settings


logger = logging.getLogger(__name__)


def llm_narration_enabled() -> bool:
    return bool(settings.MESH_LLM_NARRATION_ENABLED)


# 에이전트 종류별 인격(시스템 프롬프트). 사실 왜곡 금지 규칙은 공통으로 덧붙인다.
_PERSONA = {
    "outage_risk_agent": "너는 도시 에너지 커뮤니티의 '정전 위험 감지' 에이전트다. 시간대별 정전 빈도를 학습해 "
    "위험창에서만 배터리 예비(reserve)를 켜는 역할이다.",
    "price_agent": "너는 구역 공통 '전기요금 예측' 리드 에이전트다. 앞으로 몇 시간의 요금을 예측해 모든 건물에 알린다.",
    "carbon_agent": "너는 구역 공통 '탄소강도 예측' 리드 에이전트다. 앞으로 몇 시간의 탄소강도를 예측해 모든 건물에 알린다.",
    "_building": "너는 한 건물의 배터리 운영 에이전트다. 자기 건물의 SoC·순부하만 보고 충/방전을 결정하며, "
    "정전 시에는 비축한 배터리로 부하를 버틴다.",
}

_RULES = (
    "다음 '사실'을 바탕으로 이 에이전트가 동료들에게 보고하듯 1인칭 한국어 한 문장으로 자연스럽게 말하라. "
    "규칙: (1) 사실의 수치(행동값/SoC/예측값/reserve 등)를 절대 바꾸거나 지어내지 말 것, "
    "(2) 한 문장, 40자 내외로 간결하게, (3) 따옴표·머리말·이모지 없이 문장만 출력."
)


def _persona_for(agent_key: str) -> str:
    if agent_key.startswith("building_"):
        return _PERSONA["_building"]
    return _PERSONA.get(agent_key, "너는 도시 에너지 메시의 협력 에이전트다.")


def _facts_for(rep: Dict[str, Any]) -> str:
    """결정론적 reason + 보조 수치를 LLM ground-truth로 직렬화."""
    base = str(rep.get("reason", "")).strip()
    extra: List[str] = []
    if rep.get("role_ko"):
        extra.append(f"역할:{rep['role_ko']}")
    if rep.get("outage"):
        extra.append("현재 정전(섬 고립)")
    if "reserve_floor" in rep and rep.get("reserve_floor"):
        extra.append(f"reserve_floor:{rep['reserve_floor']}")
    suffix = f" ({', '.join(extra)})" if extra else ""
    return f"{base}{suffix}"


async def narrate_reports(reports: List[Dict[str, Any]], *, hour: int) -> List[Dict[str, Any]]:
    """각 report의 `reason`을 Qwen 생성 문장으로 교체한 새 리스트를 반환.

    비활성이면 입력을 그대로 돌려준다. 항목별 실패는 템플릿 reason으로 폴백한다.
    원본 템플릿은 `reason_template`에 보존하고, LLM 성공 여부는 `llm` 플래그로 표시한다.
    """
    if not reports or not llm_narration_enabled():
        return reports

    try:
        from openai import AsyncOpenAI
    except Exception as exc:  # pragma: no cover - openai 미설치
        logger.warning("narrate_reports: openai import 실패 → 템플릿 폴백: %s", exc)
        return reports

    client = AsyncOpenAI(base_url=settings.QWEN_BASE_URL, api_key=settings.QWEN_API_KEY or "x")
    sem = asyncio.Semaphore(max(1, int(settings.QWEN_MAX_CONCURRENCY)))

    async def _one(rep: Dict[str, Any]) -> Dict[str, Any]:
        agent_key = str(rep.get("agent", ""))
        template = str(rep.get("reason", ""))
        system = _persona_for(agent_key) + " " + _RULES
        user = f"[{hour}시] 사실: {_facts_for(rep)}"
        out = dict(rep)
        out["reason_template"] = template
        out["llm"] = False
        try:
            async with sem:
                resp = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=settings.QWEN_MODEL,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        temperature=0.7,
                        max_tokens=80,
                    ),
                    timeout=float(settings.QWEN_TIMEOUT_SECONDS),
                )
            text = (resp.choices[0].message.content or "").strip().strip('"').strip()
            text = text.splitlines()[0].strip() if text else ""
            if text:
                out["reason"] = text
                out["llm"] = True
        except Exception as exc:  # noqa: BLE001 - 항목별 폴백
            logger.debug("narrate_reports: '%s' 생성 실패 → 템플릿 폴백: %s", agent_key, exc)
        return out

    try:
        return await asyncio.gather(*[_one(r) for r in reports])
    except Exception as exc:  # noqa: BLE001 - 전체 폴백
        logger.warning("narrate_reports: 일괄 생성 실패 → 템플릿 폴백: %s", exc)
        return reports


__all__ = ["narrate_reports", "llm_narration_enabled"]
