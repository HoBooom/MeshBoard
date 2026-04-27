"""
MeshBoard — 내장 도구(MCP) 카탈로그

에이전트 크리에이터가 UI에서 선택할 수 있는 Tool(MCP) 목록을 제공하고,
langchain Tool 객체로 변환하는 레이어입니다. 실제 도구는 Python 함수로 구현되며,
초기에는 결정적(deterministic)이고 외부 상태에 영향을 주지 않는 샘플 MCP를 제공합니다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from langchain_core.tools import tool as lc_tool
from langchain_core.tools import BaseTool


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


TOOL_REGISTRY: Dict[str, BaseTool] = {
    "get_current_time": get_current_time,
    "echo": echo,
    "calculate": calculate,
    "lookup_employee_leave": lookup_employee_leave,
    "search_knowledge_base": search_knowledge_base,
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
        "id": "lookup_employee_leave",
        "name": "직원 연차 조회 (데모)",
        "description": "가상의 HR 시스템에서 사번으로 연차 잔여일을 조회합니다.",
    },
    {
        "id": "search_knowledge_base",
        "name": "사내 지식베이스 검색 (데모)",
        "description": "사내 FAQ(비밀번호/휴가/VPN/출장)에서 키워드로 정보를 찾습니다.",
    },
]


def _json_schema_for_tool(tool: BaseTool) -> Dict[str, Any]:
    """LangChain Tool 의 args_schema 를 MCP inputSchema 로 변환합니다."""
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
    meta = next((entry for entry in TOOL_CATALOG if entry["id"] == tool_id), None)
    if tool is None or meta is None:
        return None

    return {
        "name": tool_id,
        "description": meta["description"],
        "inputSchema": _json_schema_for_tool(tool),
    }


def list_mcp_tool_definitions(tool_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """요청된 도구 ID 목록을 MCP tool definition 배열로 변환합니다."""
    ids = tool_ids if tool_ids is not None else [entry["id"] for entry in TOOL_CATALOG]
    definitions: List[Dict[str, Any]] = []
    for tool_id in ids:
        definition = to_mcp_tool_definition(tool_id)
        if definition is not None:
            definitions.append(definition)
    return definitions


def list_tool_descriptors() -> List[Dict[str, Any]]:
    """Creator UI 에 노출할 도구 목록에 MCP inputSchema 를 포함해 반환합니다."""
    descriptors: List[Dict[str, Any]] = []
    for meta in TOOL_CATALOG:
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


def resolve_tools(tool_ids: List[str]) -> List[BaseTool]:
    """도구 ID 목록을 langchain Tool 인스턴스 목록으로 변환합니다.

    등록되지 않은 ID는 조용히 제외됩니다 (에이전트 실행이 중단되지 않도록).
    """
    resolved: List[BaseTool] = []
    for tool_id in tool_ids:
        if tool_id in TOOL_REGISTRY:
            resolved.append(TOOL_REGISTRY[tool_id])
    return resolved
