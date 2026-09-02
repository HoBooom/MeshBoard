"""
MeshBoard — Agent Runtime

등록된 에이전트 레코드를 기반으로 각 에이전트를 하나의 LangGraph CompiledGraph 로
컴파일하고, RunYour AI (OpenAI-호환 엔드포인트) 와 내장 도구(MCP)를 그래프 노드로
실행합니다.

RunYour AI 프록시는 GPT-5 계열 모델의 OpenAI function-calling 응답을 일관되게
전달하지 못하므로 (구조적 tool_calls 를 `null` 로 돌려주는 사례가 있음),
도구 호출 프로토콜을 LLM 이 내는 JSON 텍스트를 파싱하는 방식으로 단순화했습니다.

프로토콜
────────
LLM 은 **반드시** 아래 두 형식 중 하나로만 응답합니다.

1. 도구 사용:
   ```json
   {"action": "tool", "tool": "<tool_id>", "arguments": {...}}
   ```
2. 최종 답변:
   ```json
   {"action": "final", "answer": "<자연어 응답>"}
   ```

도구 실행 결과는 `observation` 으로 대화 로그에 추가되며, LangGraph 의
`agent_node -> mcp_tool_node -> agent_node` 전이를 통해 `final` 이 나올 때까지
최대 `MAX_TOOL_STEPS` 회 반복합니다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import operator
import re
import uuid
from functools import lru_cache
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from openai import OpenAI

from app.core.config import settings
from app.models.agent import Agent
from app.services.tool_catalog import TOOL_REGISTRY, list_mcp_tool_definitions


logger = logging.getLogger(__name__)


MAX_TOOL_STEPS = 6
GRAPH_AGENT_NODE = "agent_node"
GRAPH_TOOL_NODE = "mcp_tool_node"
GRAPH_END = "__end__"
GRAPH_NODES = {GRAPH_AGENT_NODE, GRAPH_TOOL_NODE}
AGENT_INVALID_RESPONSE_MESSAGE = "죄송합니다. 해당 AGENT가 정상적인 응답을 반환하지 못 했습니다."

_CHECKPOINTER = MemorySaver()


class AgentGraphState(TypedDict, total=False):
    """LangGraph 에 저장되는 에이전트 실행 상태."""

    messages: Annotated[List[Dict[str, Any]], operator.add]
    steps: Annotated[List[Dict[str, Any]], operator.add]
    tool_calls: Annotated[List[Dict[str, Any]], operator.add]
    transitions: Annotated[List[Dict[str, Any]], operator.add]
    parsed_action: Optional[Dict[str, Any]]
    next_tool_id: Optional[str]
    next_tool_args: Dict[str, Any]
    tool_iterations: int
    final_output: str
    error: Optional[str]


def _build_tool_manifest(tool_ids: List[str]) -> str:
    """에이전트가 선택한 도구 ID 목록을 LLM 이 읽을 수 있는 카탈로그 텍스트로 변환."""
    entries: List[str] = []
    for definition in list_mcp_tool_definitions(tool_ids):
        entries.append(
            f"- name: {definition['name']}\n"
            f"  description: {definition['description']}\n"
            f"  inputSchema: {json.dumps(definition['inputSchema'], ensure_ascii=False)}"
        )
    if not entries:
        return "(사용 가능한 도구가 없습니다. 바로 final 로 응답하세요.)"
    return "\n".join(entries)


def _build_system_prompt(agent: Agent) -> str:
    """에이전트 레코드로부터 system prompt 를 구성합니다."""
    custom_prompt = (agent.agent_card or {}).get("system_prompt")
    if custom_prompt:
        persona = custom_prompt
    else:
        parts = [
            f"당신의 이름은 '{agent.name}' (버전 {agent.version}) 입니다.",
        ]
        if agent.purpose:
            parts.append(f"역할 목적: {agent.purpose}")
        if agent.approach:
            parts.append(f"실행 방식: {agent.approach}")
        if agent.description:
            parts.append(f"상세 설명: {agent.description}")
        if agent.roles:
            parts.append(f"수행 가능한 도메인 역할: {', '.join(agent.roles)}")
        persona = "\n".join(parts)

    tool_manifest = _build_tool_manifest(list(agent.tools or []))

    protocol = (
        "### 응답 프로토콜\n"
        "당신은 반드시 아래 두 가지 JSON 형식 중 하나로만 응답해야 합니다.\n"
        "1) 도구를 사용할 때:\n"
        "   {\"action\": \"tool\", \"tool\": \"<tool_id>\", \"arguments\": {...}}\n"
        "2) 최종 답변을 할 때:\n"
        "   {\"action\": \"final\", \"answer\": \"<사용자에게 전달할 한국어 답변>\"}\n"
        "코드 블록 없이, 오직 위 JSON 한 줄만 출력하십시오. 다른 설명은 금지입니다.\n"
    )

    return (
        f"{persona}\n\n"
        "### 사용 가능한 도구 (MCP)\n"
        f"{tool_manifest}\n\n"
        f"{protocol}\n"
        "정확한 근거 없이는 임의로 답변하지 말고, 데이터가 필요한 질문에는 반드시 도구를 호출하세요."
    )


@lru_cache(maxsize=1)
def _cached_openai_client(api_key: str, base_url: str) -> OpenAI:
    """Reuse the thread-safe HTTP connection pool across agent invocations."""
    return OpenAI(api_key=api_key, base_url=base_url, timeout=60)


def _build_openai_client() -> OpenAI:
    if not settings.RUNYOUR_API_KEY:
        raise RuntimeError(
            "RUNYOUR_API_KEY 가 설정되지 않았습니다. backend/.env 파일을 확인하세요."
        )
    return _cached_openai_client(settings.RUNYOUR_API_KEY, settings.RUNYOUR_BASE_URL)


def _normalize_model_name(model_name: str) -> str:
    """RunYour AI 가 요구하는 provider/model 형식으로 모델명을 보정합니다.

    RunYour 등록명에는 version date suffix가 붙는 경우가 많아 짧은 alias를 풀이한다.
    """
    normalized = model_name.strip()
    alias = {
        "gpt-5-mini": "openai/gpt-5-mini-2025-08-07",
        "openai/gpt-5-mini": "openai/gpt-5-mini-2025-08-07",
        "gpt-5-nano": "openai/gpt-5-nano-2025-08-07",
        "openai/gpt-5-nano": "openai/gpt-5-nano-2025-08-07",
    }
    if normalized in alias:
        return alias[normalized]
    if "/" in normalized:
        return normalized
    return f"openai/{normalized}"


def _extract_json(raw: str) -> Optional[Dict[str, Any]]:
    """LLM 응답 텍스트에서 첫 번째 valid JSON object를 안전하게 뽑아냅니다.

    LLM이 한 응답에 여러 개의 JSON object를 나열하는 경우(예: tool call 3개를 newline으로 연결)에도
    첫 번째 balanced-brace object만 parse한다. 나머지는 graph의 다음 cycle에서 LLM이 재발화한다.
    """
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    # 1) 전체가 단일 JSON object이면 fast path.
    try:
        candidate = json.loads(raw)
        if isinstance(candidate, dict):
            return candidate
    except json.JSONDecodeError:
        pass

    # 2) Balanced-brace로 첫 번째 valid JSON object 찾기 (string 내 {} 무시).
    depth = 0
    start = -1
    in_str = False
    escape = False
    for idx, ch in enumerate(raw):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                snippet = raw[start:idx + 1]
                try:
                    candidate = json.loads(snippet)
                    if isinstance(candidate, dict):
                        return candidate
                except json.JSONDecodeError:
                    start = -1  # 다음 object 시도
    return None


def _call_tool(
    tool_id: str,
    arguments: Dict[str, Any],
    *,
    allowed_tool_ids: frozenset[str],
) -> str:
    """등록된 langchain Tool 을 호출하고 문자열로 결과를 반환합니다."""
    if tool_id not in allowed_tool_ids:
        return f"ERROR: 에이전트에 허용되지 않은 도구 '{tool_id}' 입니다."
    tool = TOOL_REGISTRY.get(tool_id)
    if tool is None:
        return f"ERROR: 등록되지 않은 도구 '{tool_id}' 입니다."
    try:
        result = tool.invoke(arguments or {})
    except Exception as exc:
        return f"ERROR: 도구 실행 중 오류가 발생했습니다 ({type(exc).__name__}: {exc})."
    if isinstance(result, (dict, list)):
        return json.dumps(result, ensure_ascii=False)
    return str(result)


def _transition(source: str, target: str, reason: str) -> Dict[str, Any]:
    return {"from": source, "to": target, "reason": reason}


def _route_after_agent(state: AgentGraphState) -> str:
    if state.get("error") or state.get("final_output"):
        return END
    if state.get("next_tool_id"):
        return GRAPH_TOOL_NODE
    return END


@lru_cache(maxsize=32)
def _build_agent_graph(
    client: OpenAI,
    model_name: str,
    allowed_tool_ids: tuple[str, ...],
) -> CompiledStateGraph:
    """Compile and cache a graph for a model and an exact tool allow-list."""
    allowed_tool_id_set = frozenset(allowed_tool_ids)

    def agent_node(state: AgentGraphState) -> Dict[str, Any]:
        if state.get("tool_iterations", 0) >= MAX_TOOL_STEPS:
            return {
                "final_output": (
                    f"(최대 도구 호출 횟수 {MAX_TOOL_STEPS} 회를 초과했습니다. "
                    "현재까지의 추론 결과를 기반으로 답변합니다.)"
                ),
                "transitions": [
                    _transition(GRAPH_AGENT_NODE, GRAPH_END, "max_tool_steps_exceeded")
                ],
                "next_tool_id": None,
                "next_tool_args": {},
            }

        try:
            completion = client.chat.completions.create(
                model=model_name,
                messages=state["messages"],
                # 1200은 17 building × validate JSON stringify를 담기에 부족하여 truncate 발생.
                # 4096으로 상향 (Grid-Agent 17 building 시 validate 호출이 ~2000자 차지).
                max_completion_tokens=4096,
            )
        except Exception as exc:
            logger.exception("LLM call failed")
            return {
                "error": f"{type(exc).__name__}: {exc}",
                "transitions": [_transition(GRAPH_AGENT_NODE, GRAPH_END, "llm_error")],
                "next_tool_id": None,
                "next_tool_args": {},
            }

        raw_content = (completion.choices[0].message.content or "").strip()
        parsed = _extract_json(raw_content)
        updates: Dict[str, Any] = {
            "messages": [{"role": "assistant", "content": raw_content}],
            "steps": [
                {
                    "role": "assistant",
                    "node": GRAPH_AGENT_NODE,
                    "content": raw_content,
                }
            ],
            "parsed_action": parsed,
            "next_tool_id": None,
            "next_tool_args": {},
        }

        if parsed is None:
            updates["final_output"] = raw_content or AGENT_INVALID_RESPONSE_MESSAGE
            updates["transitions"] = [
                _transition(GRAPH_AGENT_NODE, GRAPH_END, "non_json_final_fallback")
            ]
            return updates

        action = parsed.get("action")
        if action == "final":
            updates["final_output"] = str(parsed.get("answer", "")).strip() or AGENT_INVALID_RESPONSE_MESSAGE
            updates["transitions"] = [_transition(GRAPH_AGENT_NODE, GRAPH_END, "final")]
            return updates

        if action == "tool":
            tool_id = str(parsed.get("tool", "")).strip()
            arguments = parsed.get("arguments") or {}
            updates["next_tool_id"] = tool_id
            updates["next_tool_args"] = arguments if isinstance(arguments, dict) else {}
            updates["transitions"] = [
                _transition(GRAPH_AGENT_NODE, GRAPH_TOOL_NODE, "tool_requested")
            ]
            return updates

        updates["final_output"] = raw_content
        updates["transitions"] = [
            _transition(GRAPH_AGENT_NODE, GRAPH_END, "unknown_action_fallback")
        ]
        return updates

    def mcp_tool_node(state: AgentGraphState) -> Dict[str, Any]:
        tool_id = str(state.get("next_tool_id") or "").strip()
        arguments = state.get("next_tool_args") or {}
        observation = _call_tool(
            tool_id,
            arguments if isinstance(arguments, dict) else {},
            allowed_tool_ids=allowed_tool_id_set,
        )
        tool_message = {
            "role": "user",
            "content": (
                f"도구 실행 결과 ({tool_id}):\n{observation}\n\n"
                "이 결과를 바탕으로 다시 응답 프로토콜에 맞춰 한 줄 JSON 으로 대답하세요."
            ),
        }
        return {
            "messages": [tool_message],
            "steps": [
                {
                    "role": "tool",
                    "node": GRAPH_TOOL_NODE,
                    "name": tool_id,
                    "content": observation,
                }
            ],
            "tool_calls": [{"name": tool_id, "args": arguments}],
            "tool_iterations": state.get("tool_iterations", 0) + 1,
            "transitions": [
                _transition(GRAPH_TOOL_NODE, GRAPH_AGENT_NODE, "tool_observation")
            ],
            "next_tool_id": None,
            "next_tool_args": {},
        }

    graph = StateGraph(AgentGraphState)
    graph.add_node(GRAPH_AGENT_NODE, agent_node)
    graph.add_node(GRAPH_TOOL_NODE, mcp_tool_node)
    graph.set_entry_point(GRAPH_AGENT_NODE)
    graph.add_conditional_edges(
        GRAPH_AGENT_NODE,
        _route_after_agent,
        {GRAPH_TOOL_NODE: GRAPH_TOOL_NODE, END: END},
    )
    graph.add_edge(GRAPH_TOOL_NODE, GRAPH_AGENT_NODE)
    return graph.compile(
        checkpointer=_CHECKPOINTER,
        name=f"meshboard_agent_graph:{model_name}",
    )


async def invoke_agent(
    agent: Agent,
    user_message: str,
    model: Optional[str] = None,
    checkpoint_thread_id: Optional[str] = None,
    resume: bool = False,
    interrupt_after_node: Optional[str] = None,
) -> Dict[str, Any]:
    """지정한 에이전트를 실행하고, 출력·도구 호출 이력·전체 메시지 스텝을 반환합니다."""
    model_name = _normalize_model_name(model or settings.DEFAULT_LLM_MODEL)
    client = _build_openai_client()
    system_prompt = _build_system_prompt(agent)
    thread_id = checkpoint_thread_id or str(uuid.uuid4())
    allowed_tool_ids = tuple(sorted(set(agent.tools or [])))
    graph = _build_agent_graph(
        client=client,
        model_name=model_name,
        allowed_tool_ids=allowed_tool_ids,
    )
    config = {"configurable": {"thread_id": thread_id}}

    logger.info(
        "invoke_agent: agent=%s tools=%s model=%s thread_id=%s resume=%s",
        agent.name,
        list(agent.tools or []),
        model_name,
        thread_id,
        resume,
    )

    if resume and not checkpoint_thread_id:
        raise ValueError("resume=true 인 경우 checkpoint_thread_id 가 필요합니다.")

    interrupt_after = None
    if interrupt_after_node:
        if interrupt_after_node not in GRAPH_NODES:
            raise ValueError(
                f"interrupt_after_node 는 {sorted(GRAPH_NODES)} 중 하나여야 합니다."
            )
        interrupt_after = [interrupt_after_node]

    initial_state: Optional[AgentGraphState]
    if resume:
        initial_state = None
    else:
        initial_state = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "steps": [
                {"role": "system", "node": "__start__", "content": system_prompt},
                {"role": "user", "node": "__start__", "content": user_message},
            ],
            "tool_calls": [],
            "transitions": [_transition("__start__", GRAPH_AGENT_NODE, "invoke")],
            "parsed_action": None,
            "next_tool_id": None,
            "next_tool_args": {},
            "tool_iterations": 0,
            "final_output": "",
            "error": None,
        }

    # graph.invoke 와 그 내부의 OpenAI sync client 호출은 블로킹이다. 이를 event loop 에서
    # 직접 await 하면(동기 호출이므로) 17 building 병렬 invoke(asyncio.gather)가 사실상 직렬화되고,
    # asyncio.wait_for timeout 도, client 연결 끊김/서버 종료 시 cancellation 도 먹지 않는다.
    # to_thread 로 thread pool 에 넘겨 (1) gather 가 실제 병렬 실행되고 (2) timeout/cancel 이
    # 호출 대기를 중단시킬 수 있게 한다(이미 시작된 HTTP 호출 자체는 thread 에서 끝까지 진행).
    state = await asyncio.to_thread(
        graph.invoke,
        initial_state,
        config=config,
        interrupt_after=interrupt_after,
    )
    snapshot = graph.get_state(config)
    checkpoint_config = snapshot.config.get("configurable", {})

    return {
        "model_used": model_name,
        "output": state.get("final_output", ""),
        "tool_calls": state.get("tool_calls", []),
        "steps": state.get("steps", []),
        "transitions": state.get("transitions", []),
        "checkpoint": {
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_config.get("checkpoint_id"),
            "next_nodes": list(snapshot.next),
            "resumable": bool(snapshot.next),
        },
        "graph": {
            "name": f"meshboard_agent_graph:{agent.agent_id}",
            "nodes": ["__start__", GRAPH_AGENT_NODE, GRAPH_TOOL_NODE, GRAPH_END],
            "entrypoint": GRAPH_AGENT_NODE,
            "checkpointer": "MemorySaver (process-local)",
            "durable": False,
            "allowed_tool_ids": list(allowed_tool_ids),
        },
        "error": state.get("error"),
    }
