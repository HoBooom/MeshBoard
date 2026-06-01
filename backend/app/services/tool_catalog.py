"""
MeshBoard — 내장 도구(MCP) 카탈로그

에이전트 크리에이터가 UI에서 선택할 수 있는 Tool(MCP) 목록을 제공하고,
langchain Tool 객체로 변환하는 레이어입니다. 실제 도구는 Python 함수로 구현되며,
초기에는 결정적(deterministic)이고 외부 상태에 영향을 주지 않는 샘플 MCP를 제공합니다.
"""

from __future__ import annotations

import json
import math
import re
from html import unescape
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from langchain_core.tools import tool as lc_tool
from langchain_core.tools import BaseTool

from app.core.config import settings


HTTP_TIMEOUT_SECONDS = 10.0
HTTP_MAX_RESPONSE_CHARS = 6000
HTTP_USER_AGENT = "MeshBoard-AgentTool/0.1"


class InvokableTool(Protocol):
    name: str
    description: str

    def invoke(self, arguments: Dict[str, Any]) -> Any:
        ...


# ── MCP Tool Implementations ─────────────────────────────────────


@lc_tool
def get_current_time(timezone_name: str = "UTC") -> str:
    """현재 시각을 ISO 8601 형식으로 반환합니다.

    Args:
        timezone_name: 현재는 UTC 만 지원 (확장 가능).
    """
    return datetime.now(timezone.utc).isoformat()


@lc_tool
def echo(message: str) -> str:
    """입력 메시지를 그대로 돌려줍니다. 에이전트 루프 테스트용 도구입니다.

    Args:
        message: 반향할 텍스트.
    """
    return f"echo: {message}"


@lc_tool
def calculate(expression: str) -> str:
    """수학 표현식을 평가합니다. 지원: +, -, *, /, ** 및 괄호.

    Args:
        expression: 평가할 표현식 (예: '2 * (3 + 4)').
    """
    import ast
    import operator as op

    operators: Dict[type, Callable] = {
        ast.Add: op.add,
        ast.Sub: op.sub,
        ast.Mult: op.mul,
        ast.Div: op.truediv,
        ast.Pow: op.pow,
        ast.USub: op.neg,
    }

    def _eval(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp):
            return operators[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            return operators[type(node.op)](_eval(node.operand))
        raise ValueError(f"지원하지 않는 식: {ast.dump(node)}")

    try:
        tree = ast.parse(expression, mode="eval")
        return str(_eval(tree.body))
    except Exception as exc:
        return f"계산 오류: {exc}"


@lc_tool
def advanced_calculate(expression: str) -> str:
    """수학 함수와 상수를 포함한 계산식을 평가합니다.

    지원 함수: sqrt, sin, cos, tan, log, log10, exp, floor, ceil, abs, round.
    지원 상수: pi, e, tau.

    Args:
        expression: 평가할 표현식 (예: 'sqrt(81) + sin(pi / 2)').
    """
    import ast
    import operator as op

    operators: Dict[type, Callable] = {
        ast.Add: op.add,
        ast.Sub: op.sub,
        ast.Mult: op.mul,
        ast.Div: op.truediv,
        ast.FloorDiv: op.floordiv,
        ast.Mod: op.mod,
        ast.Pow: op.pow,
        ast.USub: op.neg,
        ast.UAdd: op.pos,
    }
    functions: Dict[str, Callable] = {
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "log": math.log,
        "log10": math.log10,
        "exp": math.exp,
        "floor": math.floor,
        "ceil": math.ceil,
        "abs": abs,
        "round": round,
    }
    constants = {"pi": math.pi, "e": math.e, "tau": math.tau}

    def _eval(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name) and node.id in constants:
            return constants[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in operators:
            return operators[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in operators:
            return operators[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in functions:
            args = [_eval(arg) for arg in node.args]
            if len(args) > 3:
                raise ValueError("함수 인자가 너무 많습니다.")
            return functions[node.func.id](*args)
        raise ValueError(f"지원하지 않는 식: {ast.dump(node)}")

    try:
        tree = ast.parse(expression, mode="eval")
        return str(_eval(tree.body))
    except Exception as exc:
        return f"계산 오류: {exc}"


def _trim_response(text: str, max_chars: int = HTTP_MAX_RESPONSE_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n...(truncated {len(text) - max_chars} chars)"


def _normalize_http_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("http 또는 https URL 만 사용할 수 있습니다.")
    return parsed.geturl()


def _request_text(url: str, *, params: Optional[Dict[str, Any]] = None) -> str:
    normalized_url = _normalize_http_url(url)
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True) as client:
        response = client.get(
            normalized_url,
            params=params,
            headers={"User-Agent": HTTP_USER_AGENT},
        )
        response.raise_for_status()
        return response.text


def _strip_html(text: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(without_tags)).strip()


def _duckduckgo_result_url(raw_url: str) -> str:
    decoded = unescape(raw_url)
    parsed = urlparse(decoded)
    if parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(target) if target else decoded
    return decoded


@lc_tool
def web_search(query: str, max_results: int = 5) -> str:
    """웹 검색을 수행하고 검색 결과 제목, URL, 요약을 JSON 문자열로 반환합니다.

    Args:
        query: 검색어.
        max_results: 반환할 최대 검색 결과 수. 1~8 사이로 제한됩니다.
    """
    query = query.strip()
    if not query:
        return "검색어가 비어 있습니다."
    limit = max(1, min(int(max_results or 5), 8))

    try:
        html = _request_text("https://duckduckgo.com/html/", params={"q": query})
    except Exception as exc:
        return f"웹 검색 오류: {type(exc).__name__}: {exc}"

    matches = list(
        re.finditer(
            r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
            html,
            re.IGNORECASE | re.DOTALL,
        )
    )
    snippets = [
        _strip_html(match.group(1))
        for match in re.finditer(
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
            html,
            re.IGNORECASE | re.DOTALL,
        )
    ]
    results = []
    for index, match in enumerate(matches[:limit]):
        results.append(
            {
                "title": _strip_html(match.group("title")),
                "url": _duckduckgo_result_url(match.group("href")),
                "snippet": snippets[index] if index < len(snippets) else "",
            }
        )
    if not results:
        return "검색 결과를 찾지 못했습니다."
    return json.dumps(results, ensure_ascii=False, indent=2)


@lc_tool
def fetch_url(url: str, max_chars: int = 4000) -> str:
    """HTTP/HTTPS URL 본문을 가져와 HTML 태그를 제거한 텍스트를 반환합니다.

    Args:
        url: 가져올 HTTP/HTTPS URL.
        max_chars: 반환할 최대 문자 수. 500~6000 사이로 제한됩니다.
    """
    try:
        max_len = max(500, min(int(max_chars or 4000), HTTP_MAX_RESPONSE_CHARS))
        text = _request_text(url)
        return _trim_response(_strip_html(text), max_len)
    except Exception as exc:
        return f"URL 조회 오류: {type(exc).__name__}: {exc}"


# ── CityLearn Grid-Agent MCP tools (AM-mcp-001) ─────────────────────
#
# 핵심 원칙
# - preview-only: 어떤 도구도 board snapshot이나 DB를 변경하지 않는다.
# - 입력은 string/int 등 단순 primitive. JSON object 입력은 actions_json(string)으로 통일
#   (agent_runtime의 텍스트 JSON tool protocol과 일관).
# - 출력은 항상 JSON string. token 절약을 위해 snapshot 전체가 아닌 축약 dict.
# - mapping/권한 컨텍스트가 없으므로 mapping violation은 생성하지 않는다.
#   (AM-api-001의 plan endpoint가 mapping을 알고 있는 권한 있는 경로다.)

_GRID_AGENT_TOOL_STEP_MIN = 0
_GRID_AGENT_TOOL_STEP_MAX = 8759


def _coerce_step(step: int) -> int:
    try:
        s = int(step)
    except (TypeError, ValueError):
        return _GRID_AGENT_TOOL_STEP_MIN
    return max(_GRID_AGENT_TOOL_STEP_MIN, min(_GRID_AGENT_TOOL_STEP_MAX, s))


def _grid_agent_snapshot(step: int, baseline_model: str, agent_mesh_mode: str) -> Dict[str, Any]:
    # Lazy import — tool_catalog는 backend 부팅 시 import되므로 circular 방지.
    from app.services.citylearn_board import get_board_snapshot

    valid_baselines = {"basic_rbc", "optimized_rbc", "basic_battery_rbc", "sacrbc", "sac", "marlisa"}
    valid_modes = {"not_configured", "demo_heuristic", "configured_agents", "grid_agent"}
    bm = baseline_model if baseline_model in valid_baselines else "basic_rbc"
    am = agent_mesh_mode if agent_mesh_mode in valid_modes else "demo_heuristic"
    return get_board_snapshot(step=_coerce_step(step), baseline_model=bm, agent_mesh_mode=am, window=24)  # type: ignore[arg-type]


@lc_tool
def get_citylearn_board_state(step: int = 0, baseline_model: str = "basic_rbc", agent_mesh_mode: str = "demo_heuristic") -> str:
    """현재 CityLearn board snapshot을 축약된 JSON 문자열로 반환합니다.

    Args:
        step: 조회할 time step (0~8759).
        baseline_model: basic_rbc/optimized_rbc/basic_battery_rbc/sacrbc/sac/marlisa 중 하나.
        agent_mesh_mode: not_configured/demo_heuristic/configured_agents/grid_agent 중 하나.
    """
    try:
        snapshot = _grid_agent_snapshot(step, baseline_model, agent_mesh_mode)
    except Exception as exc:
        return json.dumps({"error": f"snapshot 조회 실패: {type(exc).__name__}: {exc}"})

    buildings = [
        {
            "building_id": b.get("building_id"),
            "battery_soc": round(float(b.get("battery_soc", 0.0)), 3),
            "net_load_kwh": round(float(b.get("agent_mesh_net_load_kwh", 0.0)), 3),
            "pv_generation_kwh": round(float(b.get("pv_generation_kwh", 0.0)), 3),
        }
        for b in snapshot.get("buildings", [])
    ]
    district = sum(b["net_load_kwh"] for b in buildings)
    return json.dumps(
        {
            "step": snapshot.get("step"),
            "baseline_model": baseline_model,
            "agent_mesh_mode": agent_mesh_mode,
            "district_net_load_kwh": round(district, 3),
            "building_count": len(buildings),
            "buildings": buildings,
        },
        ensure_ascii=False,
    )


@lc_tool
def detect_citylearn_violations(step: int = 0, baseline_model: str = "basic_rbc", agent_mesh_mode: str = "demo_heuristic") -> str:
    """현재 step의 peak / ramping / soc / fairness violation 목록을 JSON 문자열로 반환합니다.

    mapping violation은 workspace 컨텍스트가 필요하므로 이 도구에서는 제외됩니다 — Grid-Agent
    plan API(권한 있는 경로)에서만 생성됩니다.

    Args:
        step: 조회할 time step (0~8759).
        baseline_model: 6개 baseline 중 하나.
        agent_mesh_mode: 4개 mode 중 하나.
    """
    from uuid import uuid4
    from app.services.citylearn_grid_agent import TopologyAnalyzer, ViolationDetector

    try:
        snapshot = _grid_agent_snapshot(step, baseline_model, agent_mesh_mode)
        topology = TopologyAnalyzer().analyze(
            workspace_id=uuid4(),
            snapshot=snapshot,
            mapping=None,
            baseline_model=baseline_model if baseline_model in {"basic_rbc", "optimized_rbc", "basic_battery_rbc", "sacrbc", "sac", "marlisa"} else None,  # type: ignore[arg-type]
            agent_mesh_mode=agent_mesh_mode if agent_mesh_mode in {"not_configured", "demo_heuristic", "configured_agents", "grid_agent"} else None,  # type: ignore[arg-type]
        )
        violations = ViolationDetector().detect_initial(topology=topology, snapshot=snapshot)
    except Exception as exc:
        return json.dumps({"error": f"violation 검출 실패: {type(exc).__name__}: {exc}"})

    return json.dumps(
        {
            "step": topology.step,
            "violations": [
                {
                    "type": v.type,
                    "building_id": v.building_id,
                    "severity": v.severity,
                    "current_value": v.current_value,
                    "limit_value": v.limit_value,
                    "description": v.description,
                }
                for v in violations
                if v.type != "mapping"  # mapping은 권한 경로에서만
            ],
        },
        ensure_ascii=False,
    )


@lc_tool
def validate_citylearn_battery_plan(actions_json: str, step: int = 0, baseline_model: str = "basic_rbc", agent_mesh_mode: str = "demo_heuristic") -> str:
    """배터리 action plan을 sandbox에서 검증하고 결과를 JSON 문자열로 반환합니다.

    Args:
        actions_json: action 배열의 JSON 문자열.
            예: '[{"building_id":"Building_1","action":-0.4,"mode":"discharge","reason":"peak shave","expected_effect":"-1.28 kWh","confidence":0.7}]'
            mode는 charge/discharge/hold, action ∈ [-1.0, 1.0], confidence ∈ [0.0, 1.0].
        step: 검증 기준 time step.
        baseline_model: 6개 baseline 중 하나.
        agent_mesh_mode: 4개 mode 중 하나.

    Returns:
        approved, score_before, score_after, feedback, remaining_violations, new_violations만 포함하는 축약 JSON.
        snapshot 전체는 반환하지 않습니다 (토큰 절약).
    """
    from uuid import uuid4
    from app.schemas.citylearn_grid_agent import CityLearnAction, CityLearnPlan
    from app.services.citylearn_grid_agent import (
        ConstraintValidator, SandboxExecutor, TopologyAnalyzer, ViolationDetector,
    )

    try:
        parsed = json.loads(actions_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"approved": False, "feedback": f"actions_json JSON 파싱 실패: {exc}"})

    if not isinstance(parsed, list):
        return json.dumps({"approved": False, "feedback": "actions_json은 action 객체의 JSON 배열이어야 합니다."})

    actions: List[CityLearnAction] = []
    for raw in parsed:
        if not isinstance(raw, dict):
            return json.dumps({"approved": False, "feedback": "각 action은 JSON object여야 합니다."})
        try:
            actions.append(CityLearnAction(**raw))
        except Exception as exc:
            return json.dumps({"approved": False, "feedback": f"action 스키마 검증 실패: {exc}"})

    plan = CityLearnPlan(
        strategy_summary="(LLM tool call) sandbox validation request",
        actions=actions,
        risk_assessment="(LLM tool call)",
    )

    try:
        snapshot = _grid_agent_snapshot(step, baseline_model, agent_mesh_mode)
        analyzer = TopologyAnalyzer()
        topology_before = analyzer.analyze(
            workspace_id=uuid4(), snapshot=snapshot, mapping=None,
            baseline_model=baseline_model if baseline_model in {"basic_rbc", "optimized_rbc", "basic_battery_rbc", "sacrbc", "sac", "marlisa"} else None,  # type: ignore[arg-type]
            agent_mesh_mode=agent_mesh_mode if agent_mesh_mode in {"not_configured", "demo_heuristic", "configured_agents", "grid_agent"} else None,  # type: ignore[arg-type]
        )
        initial_violations = ViolationDetector().detect_initial(topology=topology_before, snapshot=snapshot)
        sandbox = SandboxExecutor().execute(snapshot=snapshot, plan=plan)
        topology_after = analyzer.analyze(
            workspace_id=uuid4(), snapshot=sandbox, mapping=None,
            baseline_model=baseline_model if baseline_model in {"basic_rbc", "optimized_rbc", "basic_battery_rbc", "sacrbc", "sac", "marlisa"} else None,  # type: ignore[arg-type]
            agent_mesh_mode=agent_mesh_mode if agent_mesh_mode in {"not_configured", "demo_heuristic", "configured_agents", "grid_agent"} else None,  # type: ignore[arg-type]
        )
        result = ConstraintValidator().validate(
            snapshot_before=snapshot,
            snapshot_after=sandbox,
            topology_before=topology_before,
            topology_after=topology_after,
            plan=plan,
            initial_violations=initial_violations,
        )
    except Exception as exc:
        return json.dumps({"approved": False, "feedback": f"sandbox 실행 실패: {type(exc).__name__}: {exc}"})

    return json.dumps(
        {
            "approved": result.approved,
            "status": result.status,
            "score_before": result.score_before,
            "score_after": result.score_after,
            "feedback": result.feedback,
            "forbidden_action_keys": result.forbidden_action_keys,
            "remaining_violations": [
                {"type": v.type, "building_id": v.building_id, "description": v.description}
                for v in result.remaining_violations
            ],
            "new_violations": [
                {"type": v.type, "building_id": v.building_id, "description": v.description}
                for v in result.new_violations
            ],
        },
        ensure_ascii=False,
    )


@lc_tool
def lookup_employee_leave(employee_id: str) -> str:
    """직원의 연차 잔여일 정보를 조회합니다 (데모용 고정 데이터).

    Args:
        employee_id: 직원 사번.
    """
    mock_db = {
        "E001": {"name": "김하늘", "remaining_days": 11, "used_days": 4},
        "E002": {"name": "이바다", "remaining_days": 7, "used_days": 8},
        "E003": {"name": "박구름", "remaining_days": 15, "used_days": 0},
    }
    record = mock_db.get(employee_id.upper())
    if not record:
        return f"사번 {employee_id} 에 해당하는 직원 정보를 찾을 수 없습니다."
    return (
        f"{record['name']} 님의 남은 연차는 {record['remaining_days']}일, "
        f"사용한 연차는 {record['used_days']}일 입니다."
    )


@lc_tool
def search_knowledge_base(query: str) -> str:
    """사내 지식베이스를 검색한 것처럼 응답합니다 (데모용 고정 데이터).

    Args:
        query: 검색어.
    """
    kb = {
        "비밀번호": "비밀번호는 내부 포털 → 계정 → 비밀번호 변경 에서 재설정할 수 있습니다.",
        "휴가": "연차 휴가는 근무일 기준 3일 전 사전 승인이 필요합니다.",
        "vpn": "VPN 접속은 IT 포털에서 2FA 등록 후 FortiClient 를 통해 가능합니다.",
        "출장": "국내 출장비는 일일 한도 7만원, 해외 출장비는 정책 문서 HR-003 을 참고하세요.",
    }
    for keyword, answer in kb.items():
        if keyword.lower() in query.lower():
            return answer
    return "관련 문서를 찾을 수 없습니다. IT 헬프데스크 혹은 HR 팀에 직접 문의해 주세요."


# ── Public Catalog ───────────────────────────────────────────────


TOOL_REGISTRY: Dict[str, InvokableTool] = {
    "get_current_time": get_current_time,
    "echo": echo,
    "calculate": calculate,
    "advanced_calculate": advanced_calculate,
    "web_search": web_search,
    "fetch_url": fetch_url,
    "lookup_employee_leave": lookup_employee_leave,
    "search_knowledge_base": search_knowledge_base,
    "get_citylearn_board_state": get_citylearn_board_state,
    "detect_citylearn_violations": detect_citylearn_violations,
    "validate_citylearn_battery_plan": validate_citylearn_battery_plan,
}


TOOL_CATALOG: List[Dict[str, str]] = [
    {
        "id": "get_current_time",
        "name": "현재 시각 조회",
        "description": "현재 UTC 시각을 ISO 8601 형식으로 반환합니다.",
    },
    {
        "id": "echo",
        "name": "에코(Echo)",
        "description": "입력된 메시지를 그대로 반환합니다. 동작 테스트용 도구입니다.",
    },
    {
        "id": "calculate",
        "name": "수식 계산",
        "description": "숫자 표현식을 평가합니다. 예: 2 * (3 + 4).",
    },
    {
        "id": "advanced_calculate",
        "name": "고급 수학 계산",
        "description": "sqrt, sin, log, pi 같은 수학 함수/상수를 포함한 계산식을 평가합니다.",
    },
    {
        "id": "web_search",
        "name": "웹 검색",
        "description": "외부 웹 검색 결과를 제목, URL, 요약 형태로 반환합니다.",
    },
    {
        "id": "fetch_url",
        "name": "URL 본문 조회",
        "description": "HTTP/HTTPS URL을 가져와 HTML 태그를 제거한 텍스트를 반환합니다.",
    },
    {
        "id": "lookup_employee_leave",
        "name": "직원 연차 조회 (데모)",
        "description": "가상의 HR 시스템에서 사번으로 연차 잔여일을 조회합니다.",
    },
    {
        "id": "search_knowledge_base",
        "name": "사내 지식베이스 검색 (데모)",
        "description": "사내 FAQ(비밀번호/휴가/VPN/출장)에서 키워드로 정보를 찾습니다.",
    },
    {
        "id": "get_citylearn_board_state",
        "name": "CityLearn Board 상태 조회",
        "description": "Grid-Agent용: 지정 step의 CityLearn board snapshot을 축약 JSON으로 반환합니다 (district load + building 17개의 SOC/net_load/PV).",
    },
    {
        "id": "detect_citylearn_violations",
        "name": "CityLearn Violation 검출",
        "description": "Grid-Agent용: peak/ramping/soc/fairness violation을 JSON으로 반환합니다. mapping violation은 권한 있는 plan API에서만 노출됩니다.",
    },
    {
        "id": "validate_citylearn_battery_plan",
        "name": "CityLearn 배터리 Plan 검증",
        "description": "Grid-Agent용: actions_json 문자열을 sandbox에서 검증하여 approved/score_before/score_after/feedback/forbidden_action_keys/violations를 반환합니다. 적용은 하지 않습니다 (preview-only).",
    },
]


class ExternalHttpTool:
    """환경변수로 등록되는 HTTP 기반 외부 MCP 호환 도구 어댑터."""

    def __init__(self, config: Dict[str, Any]):
        self.name = str(config["id"]).strip()
        self.description = str(config.get("description") or config.get("name") or self.name)
        self.input_schema = config.get("inputSchema") or config.get("input_schema") or {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }
        self.url = str(config["url"]).strip()
        self.method = str(config.get("method") or "POST").upper()
        self.headers = dict(config.get("headers") or {})
        self.timeout_seconds = float(config.get("timeout_seconds") or HTTP_TIMEOUT_SECONDS)

    def invoke(self, arguments: Dict[str, Any]) -> str:
        _normalize_http_url(self.url)
        if self.method not in {"GET", "POST"}:
            return f"ERROR: 지원하지 않는 외부 도구 HTTP method 입니다: {self.method}"
        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                headers = {"User-Agent": HTTP_USER_AGENT, **self.headers}
                if self.method == "GET":
                    response = client.get(self.url, params=arguments or {}, headers=headers)
                else:
                    response = client.post(self.url, json=arguments or {}, headers=headers)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    return json.dumps(response.json(), ensure_ascii=False)
                return _trim_response(response.text)
        except Exception as exc:
            return f"ERROR: 외부 도구 실행 실패 ({type(exc).__name__}: {exc})."


def _load_external_tool_configs() -> List[Dict[str, Any]]:
    try:
        configs = json.loads(settings.EXTERNAL_MCP_TOOLS or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(configs, list):
        return []
    valid_configs = []
    for config in configs:
        if not isinstance(config, dict):
            continue
        tool_id = str(config.get("id") or "").strip()
        url = str(config.get("url") or "").strip()
        if not tool_id or not url or tool_id in TOOL_REGISTRY:
            continue
        valid_configs.append(config)
    return valid_configs


EXTERNAL_TOOL_CATALOG: List[Dict[str, Any]] = []
for external_config in _load_external_tool_configs():
    external_tool = ExternalHttpTool(external_config)
    TOOL_REGISTRY[external_tool.name] = external_tool  # type: ignore[assignment]
    EXTERNAL_TOOL_CATALOG.append(
        {
            "id": external_tool.name,
            "name": str(external_config.get("name") or external_tool.name),
            "description": external_tool.description,
            "inputSchema": external_tool.input_schema,
        }
    )


def _json_schema_for_tool(tool: InvokableTool) -> Dict[str, Any]:
    """LangChain Tool 의 args_schema 를 MCP inputSchema 로 변환합니다."""
    external_schema = getattr(tool, "input_schema", None)
    if isinstance(external_schema, dict):
        return external_schema
    schema = getattr(tool, "args_schema", None)
    if schema is None or not hasattr(schema, "model_json_schema"):
        return {"type": "object", "properties": {}, "additionalProperties": False}
    try:
        raw_schema = schema.model_json_schema()
    except Exception:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    return {
        "type": "object",
        "properties": raw_schema.get("properties") or {},
        "required": raw_schema.get("required") or [],
        "additionalProperties": raw_schema.get("additionalProperties", False),
    }


def to_mcp_tool_definition(tool_id: str) -> Optional[Dict[str, Any]]:
    """내장 도구를 MCP tool definition 규격(name/description/inputSchema)으로 반환합니다."""
    tool = TOOL_REGISTRY.get(tool_id)
    meta = next((entry for entry in [*TOOL_CATALOG, *EXTERNAL_TOOL_CATALOG] if entry["id"] == tool_id), None)
    if tool is None or meta is None:
        return None

    return {
        "name": tool_id,
        "description": meta["description"],
        "inputSchema": _json_schema_for_tool(tool),
    }


def list_mcp_tool_definitions(tool_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """요청된 도구 ID 목록을 MCP tool definition 배열로 변환합니다."""
    ids = tool_ids if tool_ids is not None else [entry["id"] for entry in [*TOOL_CATALOG, *EXTERNAL_TOOL_CATALOG]]
    definitions: List[Dict[str, Any]] = []
    for tool_id in ids:
        definition = to_mcp_tool_definition(tool_id)
        if definition is not None:
            definitions.append(definition)
    return definitions


def list_tool_descriptors() -> List[Dict[str, Any]]:
    """Creator UI 에 노출할 도구 목록에 MCP inputSchema 를 포함해 반환합니다."""
    descriptors: List[Dict[str, Any]] = []
    for meta in [*TOOL_CATALOG, *EXTERNAL_TOOL_CATALOG]:
        definition = to_mcp_tool_definition(meta["id"])
        if definition is None:
            continue
        descriptors.append(
            {
                **meta,
                "parameters": definition["inputSchema"],
                "mcp_definition": definition,
            }
        )
    return descriptors


def resolve_tools(tool_ids: List[str]) -> List[InvokableTool]:
    """도구 ID 목록을 langchain Tool 인스턴스 목록으로 변환합니다.

    등록되지 않은 ID는 조용히 제외됩니다 (에이전트 실행이 중단되지 않도록).
    """
    resolved: List[InvokableTool] = []
    for tool_id in tool_ids:
        if tool_id in TOOL_REGISTRY:
            resolved.append(TOOL_REGISTRY[tool_id])
    return resolved
