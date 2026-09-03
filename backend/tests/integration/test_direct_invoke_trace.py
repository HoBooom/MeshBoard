"""에이전트 직접 호출도 실행 트리를 남기는지 검증한다.

회귀 방지: 예전에는 `Interaction` 을 브로커만 기록해서, `POST /agents/{id}/invoke` 로 실행하면
운영 화면에서 아무 흔적도 볼 수 없었다. 진입점에 따라 추적 가능 여부가 갈리면 안 된다.
"""

from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import select

from app.models.interaction import Interaction
from app.models.policy import AgentPolicy, Policy

from .test_rbac_enforcement import ApiTestCase


async def _fake_invoke(**kwargs):
    return {
        "model_used": "test-model",
        "usage": {"input_tokens": 31, "output_tokens": 12},
        "output": "직접 호출 응답",
        "tool_calls": [],
        "steps": [
            {"node": "agent_node", "content": "생각함"},
            {"node": "mcp_tool_node", "name": "calculate", "content": "42"},
        ],
        "transitions": [],
        "checkpoint": {"thread_id": "t", "checkpoint_id": None, "next_nodes": [], "resumable": False},
        "graph": {"durable": False},
        "error": None,
    }


class DirectInvokeTraceTests(ApiTestCase):
    async def _tree(self, execution_tree_id):
        return (
            await self.session.execute(
                select(Interaction)
                .where(Interaction.execution_tree_id == execution_tree_id)
                .order_by(Interaction.tree_depth, Interaction.step_id)
            )
        ).scalars().all()

    async def test_invoke_records_a_tree_and_returns_its_id(self) -> None:
        owner = await self.make_user()
        agent = await self.make_agent(owner, tools=["calculate"])

        with patch("app.api.v1.agents.invoke_agent", _fake_invoke):
            response = await self.client.post(
                f"/api/v1/agents/{agent.agent_id}/invoke",
                json={"message": "2 더하기 2는?"},
                headers=self.auth(owner),
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["usage"], {"input_tokens": 31, "output_tokens": 12})

        rows = await self._tree(body["execution_tree_id"])
        self.assertEqual([r.tree_depth for r in rows], [0, 1, 2, 2])
        kinds = [r.kind for r in rows]
        self.assertEqual(kinds, ["message", "handoff", "reasoning", "tool_result"])

        root, handoff = rows[0], rows[1]
        self.assertEqual(handoff.parent_id, root.interaction_id)
        self.assertTrue(str(handoff.tree_path).startswith(str(root.tree_path)))
        self.assertEqual(handoff.state, "COMPLETED")
        # 워크스페이스 대화에 속하지 않는 실행이므로 conversation 은 비어 있어야 한다.
        self.assertIsNone(root.conversation_id)

    async def test_invoke_persists_model_and_token_usage_on_the_handoff(self) -> None:
        owner = await self.make_user()
        agent = await self.make_agent(owner)

        with patch("app.api.v1.agents.invoke_agent", _fake_invoke):
            response = await self.client.post(
                f"/api/v1/agents/{agent.agent_id}/invoke",
                json={"message": "사용량 확인"},
                headers=self.auth(owner),
            )

        handoff = (
            await self.session.execute(
                select(Interaction).where(
                    Interaction.execution_tree_id == response.json()["execution_tree_id"],
                    Interaction.kind == "handoff",
                )
            )
        ).scalar_one()
        self.assertEqual(handoff.model_used, "test-model")
        self.assertEqual((handoff.token_input, handoff.token_output), (31, 12))

    async def test_policy_blocked_invoke_is_still_recorded(self) -> None:
        owner = await self.make_user()
        agent = await self.make_agent(owner)
        policy = Policy(
            name="direct-invoke-guard",
            template={"blocked_terms": ["비밀번호"]},
            status="ACTIVE",
        )
        self.session.add(policy)
        await self.session.flush()
        self.session.add(AgentPolicy(agent_id=agent.agent_id, policy_id=policy.policy_id))
        await self.session.flush()

        with patch("app.api.v1.agents.invoke_agent", _fake_invoke):
            response = await self.client.post(
                f"/api/v1/agents/{agent.agent_id}/invoke",
                json={"message": "비밀번호 알려줘"},
                headers=self.auth(owner),
            )

        self.assertEqual(response.status_code, 403)
        blocked = (
            await self.session.execute(
                select(Interaction).where(
                    Interaction.kind == "handoff",
                    Interaction.target_id == agent.agent_id,
                )
            )
        ).scalars().all()
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].state, "CANCELLED")
        self.assertEqual(blocked[0].error_code, "POLICY_BLOCKED")
