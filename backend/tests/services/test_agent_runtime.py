"""Agent runtime protocol and tool-boundary tests without an external LLM."""

from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from app.services import agent_runtime


class _FakeCompletions:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)

    def create(self, **_: object) -> SimpleNamespace:
        content = next(self.responses)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class _FakeClient:
    def __init__(self, responses: list[str]) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(responses))


def _agent(*, tools: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        agent_id=uuid4(),
        name="Runtime Test Agent",
        version="1.0.0",
        purpose="tool boundary verification",
        approach=None,
        description=None,
        roles=["test"],
        tools=tools,
        agent_card={},
    )


class AgentRuntimeTests(unittest.TestCase):
    def tearDown(self) -> None:
        agent_runtime._build_agent_graph.cache_clear()
        agent_runtime._cached_openai_client.cache_clear()

    def test_extract_json_accepts_fenced_and_embedded_object(self) -> None:
        fenced = '```json\n{"action":"final","answer":"ok"}\n```'
        embedded = 'prefix {"action":"tool","tool":"echo","arguments":{}} suffix'

        self.assertEqual(agent_runtime._extract_json(fenced)["answer"], "ok")
        self.assertEqual(agent_runtime._extract_json(embedded)["tool"], "echo")

    def test_tool_call_rejects_global_tool_outside_agent_allow_list(self) -> None:
        result = agent_runtime._call_tool(
            "calculate",
            {"expression": "2 + 2"},
            allowed_tool_ids=frozenset({"echo"}),
        )

        self.assertIn("허용되지 않은 도구", result)
        self.assertNotIn("4", result)

    def test_invoke_executes_allowed_tool_and_reuses_compiled_graph(self) -> None:
        fake_client = _FakeClient(
            [
                json.dumps(
                    {"action": "tool", "tool": "echo", "arguments": {"message": "hello"}}
                ),
                json.dumps({"action": "final", "answer": "echo completed"}),
            ]
        )
        test_agent = _agent(tools=["echo"])

        with patch.object(agent_runtime, "_build_openai_client", return_value=fake_client):
            result = asyncio.run(
                agent_runtime.invoke_agent(test_agent, "say hello", model="test/model")
            )
            graph_first = agent_runtime._build_agent_graph(
                fake_client,
                "test/model",
                ("echo",),
            )
            graph_second = agent_runtime._build_agent_graph(
                fake_client,
                "test/model",
                ("echo",),
            )

        self.assertEqual(result["output"], "echo completed")
        self.assertEqual(result["tool_calls"], [{"name": "echo", "args": {"message": "hello"}}])
        self.assertEqual(result["graph"]["allowed_tool_ids"], ["echo"])
        self.assertIs(graph_first, graph_second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
