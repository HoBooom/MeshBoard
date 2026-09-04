"""
MeshBoard — Agent Runtime

등록된 에이전트 레코드를 기반으로 각 에이전트를 하나의 LangGraph CompiledGraph 로
컴파일하고, OpenAI-호환 LLM 엔드포인트와 내장 도구(MCP)를 그래프 노드로 실행합니다.

LLM 백엔드
──────────
기본값은 **로컬 Ollama**(`http://localhost:11434/v1`, `qwen3:8b`)입니다. 클론한 사람이
API 키 없이 바로 실행할 수 있고, 유료 호출이 발생하지 않습니다. `LLM_BASE_URL` /
`LLM_MODEL` 만 바꾸면 vLLM·LM Studio·OpenAI·게이트웨이 등 어떤 OpenAI-호환 백엔드로도
교체됩니다 (`backend/.env.example` 참고).

도구 호출은 OpenAI function-calling 대신 **LLM 이 내는 JSON 텍스트를 파싱**하는 방식으로
단순화했습니다. 소형 로컬 모델과 일부 게이트웨이가 구조적 `tool_calls` 를 일관되게
돌려주지 못하기 때문이며(`null` 반환 사례), 이 방식은 백엔드 종류와 무관하게 동작합니다.

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
from collections import OrderedDict
from functools import lru_cache
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from openai import OpenAI

from app.core.config import settings
from app.models.agent import Agent
from app.services.tool_catalog import TOOL_REGISTRY, list_mcp_tool_definitions
from app.services.runtime_control import AgentExecutionCancelled, runtime_control


logger = logging.getLogger(__name__)


MAX_TOOL_STEPS = 6
GRAPH_AGENT_NODE = "agent_node"
GRAPH_TOOL_NODE = "mcp_tool_node"
GRAPH_END = "__end__"
GRAPH_NODES = {GRAPH_AGENT_NODE, GRAPH_TOOL_NODE}
AGENT_INVALID_RESPONSE_MESSAGE = "죄송합니다. 해당 AGENT가 정상적인 응답을 반환하지 못 했습니다."

_CHECKPOINTER = MemorySaver()

# MemorySaver 는 프로세스 메모리에 체크포인트를 쌓기만 하고 스스로 비우지 않는다.
# invoke 마다 새 thread_id 가 생기므로 그대로 두면 장시간 구동 시 메모리가 단조 증가한다.
# 끝난 실행은 즉시 버리고, 재개 가능한(interrupt 된) 실행만 최근 것부터 이만큼 유지한다.
MAX_RESUMABLE_CHECKPOINTS = 128
_resumable_threads: "OrderedDict[str, None]" = OrderedDict()


def _drop_checkpoint_thread(thread_id: str) -> None:
    try:
        _CHECKPOINTER.delete_thread(thread_id)
    except Exception:  # noqa: BLE001 — 정리 실패가 실행 결과를 망가뜨리면 안 된다.
        logger.debug("Failed to drop checkpoint thread %s", thread_id, exc_info=True)


def _retain_checkpoint_thread(thread_id: str, *, resumable: bool) -> None:
    """실행이 끝난 뒤 체크포인트를 버릴지 남길지 결정합니다.

    재개할 수 없는 실행의 체크포인트는 쓸모가 없으므로 바로 버린다.
    재개 가능한 실행은 남기되 총량을 제한해, 아무도 resume 하지 않은 오래된 것부터 정리한다.
    """
    if not resumable:
        _resumable_threads.pop(thread_id, None)
        _drop_checkpoint_thread(thread_id)
        return

    _resumable_threads[thread_id] = None
    _resumable_threads.move_to_end(thread_id)
    while len(_resumable_threads) > MAX_RESUMABLE_CHECKPOINTS:
        oldest, _ = _resumable_threads.popitem(last=False)
        _drop_checkpoint_thread(oldest)


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
    # 한 invoke 안에서 agent_node 가 여러 번 돌 수 있으므로 토큰은 누적한다.
    token_input: Annotated[int, operator.add]
    token_output: Annotated[int, operator.add]


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


def _build_system_prompt(agent: Agent, tool_ids: Optional[list[str]] = None) -> str:
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

    tool_manifest = _build_tool_manifest(tool_ids if tool_ids is not None else list(agent.tools or []))

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


@lru_cache(maxsize=4)
def _cached_openai_client(api_key: str, base_url: str, timeout: float) -> OpenAI:
    """Reuse the thread-safe HTTP connection pool across agent invocations."""
    return OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)


def _build_openai_client() -> OpenAI:
    """OpenAI-호환 클라이언트를 만듭니다.

    기본값은 로컬 서버(Ollama)이므로 API 키 없이도 동작합니다. 외부 게이트웨이를 쓰도록
    설정한 경우에만 키를 요구합니다.
    """
    api_key = settings.llm_api_key
    if settings.llm_uses_external_gateway and not api_key:
        raise RuntimeError(
            "외부 LLM 게이트웨이가 선택됐지만 RUNYOUR_API_KEY 가 비어 있습니다. "
            "backend/.env 를 확인하거나, 값을 비워 로컬 모델을 사용하세요."
        )
    return _cached_openai_client(
        api_key, settings.llm_base_url, float(settings.LLM_TIMEOUT_SECONDS)
    )


def _normalize_model_name(model_name: str) -> str:
    """설정된 별칭만 치환하고 나머지는 모델명을 그대로 전달합니다.

    Ollama 는 `qwen2.5:7b` 처럼 provider 접두가 없고, OpenRouter 계열 게이트웨이는
    `openai/gpt-5` 처럼 접두를 요구합니다. 어느 쪽이든 사용자가 적은 문자열을 그대로
    보내는 것이 안전하므로, 접두를 임의로 붙이지 않습니다.
    """
    normalized = model_name.strip()
    return settings.llm_model_aliases.get(normalized, normalized)


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


def _create_completion(client: OpenAI, model_name: str, messages: List[Dict[str, Any]]):
    """출력 길이 상한 파라미터 이름이 서버마다 달라 두 형태를 모두 시도합니다.

    OpenAI 최신 모델(GPT-5 계열)은 `max_completion_tokens` 만 받고, Ollama/vLLM 등
    다수의 OpenAI-호환 로컬 서버는 `max_tokens` 만 받습니다. 어느 쪽이든 동작하도록
    최신 이름을 먼저 시도하고, 서버가 거부하면 legacy 이름으로 한 번 재시도합니다.
    """
    limit = int(settings.LLM_MAX_OUTPUT_TOKENS)
    extra = {}
    effort = settings.LLM_REASONING_EFFORT.strip()
    if effort:
        extra["reasoning_effort"] = effort

    attempts = [
        {"max_completion_tokens": limit, **extra},
        {"max_tokens": limit, **extra},
    ]
    # reasoning_effort 를 모르는 서버도 있으므로 마지막에는 빼고 한 번 더 시도한다.
    if extra:
        attempts.append({"max_tokens": limit})

    last_error: Exception | None = None
    for index, kwargs in enumerate(attempts):
        try:
            return client.chat.completions.create(
                model=model_name, messages=messages, **kwargs
            )
        except TypeError as exc:  # 설치된 SDK 가 해당 인자를 모르는 경우.
            last_error = exc
        except Exception as exc:  # noqa: BLE001
            # 파라미터 거부로 보이지 않으면 그대로 올린다. 마지막 시도도 마찬가지.
            message = str(exc)
            rejected = any(
                key in message for key in ("max_completion_tokens", "max_tokens", "reasoning_effort")
            )
            if not rejected or index == len(attempts) - 1:
                raise
            logger.debug("Retrying completion without rejected parameters: %s", message[:200])
            last_error = exc
    raise last_error  # pragma: no cover — attempts 는 항상 비어있지 않다.


def _usage_tokens(completion: Any) -> tuple[int, int]:
    """completion 의 usage 를 (prompt, completion) 토큰 수로 뽑아냅니다.

    OpenAI·Ollama·vLLM 모두 `usage.prompt_tokens` / `usage.completion_tokens` 를 채워 주지만,
    일부 OpenAI-호환 서버는 usage 를 아예 생략합니다. 그 경우 0 으로 처리해 집계가 조용히
    잘못된 값을 만들지 않게 합니다(0 은 "측정되지 않음"으로 읽힌다).
    """
    usage = getattr(completion, "usage", None)
    if usage is None:
        return 0, 0

    def _as_int(value: Any) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    return _as_int(getattr(usage, "prompt_tokens", 0)), _as_int(
        getattr(usage, "completion_tokens", 0)
    )


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
            completion = _create_completion(client, model_name, state["messages"])
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
        prompt_tokens, completion_tokens = _usage_tokens(completion)
        updates: Dict[str, Any] = {
            "token_input": prompt_tokens,
            "token_output": completion_tokens,
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
    allowed_tool_ids_override: Optional[set[str] | frozenset[str]] = None,
) -> Dict[str, Any]:
    """지정한 에이전트를 실행하고, 출력·도구 호출 이력·전체 메시지 스텝을 반환합니다."""
    model_name = _normalize_model_name(model or settings.llm_default_model)
    client = _build_openai_client()
    allowed_tool_ids = tuple(
        sorted(
            set(agent.tools or [])
            if allowed_tool_ids_override is None
            else set(agent.tools or []).intersection(allowed_tool_ids_override)
        )
    )
    system_prompt = _build_system_prompt(agent, list(allowed_tool_ids))
    thread_id = checkpoint_thread_id or str(uuid.uuid4())
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
            "token_input": 0,
            "token_output": 0,
        }

    # graph.invoke 와 그 내부의 OpenAI sync client 호출은 블로킹이다. 이를 event loop 에서
    # 직접 await 하면(동기 호출이므로) 17 building 병렬 invoke(asyncio.gather)가 사실상 직렬화되고,
    # asyncio.wait_for timeout 도, client 연결 끊김/서버 종료 시 cancellation 도 먹지 않는다.
    # to_thread 로 thread pool 에 넘겨 (1) gather 가 실제 병렬 실행되고 (2) timeout/cancel 이
    # 호출 대기를 중단시킬 수 있게 한다(이미 시작된 HTTP 호출 자체는 thread 에서 끝까지 진행).
    cancellation_event = runtime_control.begin(agent.agent_id)
    if cancellation_event.is_set():
        runtime_control.end(agent.agent_id)
        raise AgentExecutionCancelled("에이전트가 운영자에 의해 중지되었습니다.")
    graph_task = asyncio.create_task(
        asyncio.to_thread(
            graph.invoke,
            initial_state,
            config=config,
            interrupt_after=interrupt_after,
        )
    )
    cancellation_task = asyncio.create_task(cancellation_event.wait())
    try:
        completed, _ = await asyncio.wait(
            {graph_task, cancellation_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if cancellation_task in completed and cancellation_event.is_set():
            graph_task.cancel()
            raise AgentExecutionCancelled("에이전트가 운영자에 의해 중지되었습니다.")
        cancellation_task.cancel()
        state = await graph_task
    finally:
        cancellation_task.cancel()
        runtime_control.end(agent.agent_id)
    snapshot = graph.get_state(config)
    checkpoint_config = snapshot.config.get("configurable", {})
    _retain_checkpoint_thread(thread_id, resumable=bool(snapshot.next))

    return {
        "model_used": model_name,
        "usage": {
            "input_tokens": int(state.get("token_input", 0) or 0),
            "output_tokens": int(state.get("token_output", 0) or 0),
        },
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
