"""브로커 라우팅 통합 테스트.

`route_workspace_message` 는 이 프로젝트에서 가장 중요한 경로다 — 타겟 해소, receipt 생성,
정책 강제, ltree 실행 트리 기록, 병렬 fan-out 이 전부 여기서 일어난다.
실제 PostgreSQL 없이는 ltree 경로도 ARRAY 컬럼도 검증할 수 없어 통합 테스트로 다룬다.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models.interaction import Interaction
from app.models.message import MessageReceipt
from app.models.policy import AgentPolicy, Policy
from app.schemas.message import PublishMessageRequest
from app.services.message_broker import publish_message_header, route_workspace_message

from ._harness import PostgresTestCase


def _fake_invoker(answer: str = "ok", *, input_tokens: int = 11, output_tokens: int = 7):
    """invoke_agent 의 반환 계약만 흉내내는 대역. LLM 을 부르지 않는다."""

    async def invoke(agent, user_message, allowed_tool_ids_override=None):
        return {
            "model_used": "test-model",
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            "output": f"{answer}:{agent.name}",
            "tool_calls": [],
            "steps": [{"node": "agent_node", "content": "reasoned"}],
            "transitions": [],
            "error": None,
        }

    return invoke


class BrokerRoutingTests(PostgresTestCase):
    async def _publish(self, *, sender, workspace, message: str, **overrides):
        payload = PublishMessageRequest(
            sender_type="user",
            sender_id=sender.user_id,
            domain="ops",
            intent="request",
            scope="workspace",
            workspace_id=workspace.workspace_id,
            payload={"message": message},
            **overrides,
        )
        return await publish_message_header(
            self.session, payload, sender_id=sender.user_id, sender_name=sender.name
        )

    async def test_direct_mention_routes_only_to_the_named_agent(self) -> None:
        owner = await self.make_user()
        workspace = await self.make_workspace(owner)
        alpha = await self.make_agent(owner, name="Alpha Bot")
        beta = await self.make_agent(owner, name="Beta Bot")
        await self.place_agent(workspace, alpha)
        await self.place_agent(workspace, beta)

        header = await self._publish(sender=owner, workspace=workspace, message="@alpha_bot 확인 부탁")
        routing = await route_workspace_message(
            self.session, header, agent_invoker=_fake_invoker()
        )

        self.assertEqual(routing["matched_agent_ids"], [alpha.agent_id])
        self.assertIn(beta.agent_id, routing["ignored_agent_ids"])

    async def test_subscription_edge_routes_when_no_mention_is_present(self) -> None:
        owner = await self.make_user()
        workspace = await self.make_workspace(owner)
        watcher = await self.make_agent(owner, name="Watcher Bot")
        bystander = await self.make_agent(owner, name="Bystander Bot")
        watcher_node = await self.place_agent(workspace, watcher)
        await self.place_agent(workspace, bystander)
        sender_node = await self.add_user_node(workspace, owner)
        await self.subscribe(workspace, subscriber=watcher_node, publisher=sender_node)

        header = await self._publish(sender=owner, workspace=workspace, message="구독자만 받아야 합니다")
        routing = await route_workspace_message(
            self.session, header, agent_invoker=_fake_invoker()
        )

        self.assertEqual(routing["matched_agent_ids"], [watcher.agent_id])
        self.assertIn(bystander.agent_id, routing["ignored_agent_ids"])

    async def test_explicit_role_target_selects_agents_by_role(self) -> None:
        owner = await self.make_user()
        workspace = await self.make_workspace(owner)
        analyst = await self.make_agent(owner, name="Analyst Bot", roles=["analyst"])
        writer = await self.make_agent(owner, name="Writer Bot", roles=["writer"])
        await self.place_agent(workspace, analyst)
        await self.place_agent(workspace, writer)

        header = await self._publish(
            sender=owner, workspace=workspace, message="역할 지정 요청", target_roles=["analyst"]
        )
        routing = await route_workspace_message(
            self.session, header, agent_invoker=_fake_invoker()
        )

        self.assertEqual(routing["matched_agent_ids"], [analyst.agent_id])

    async def test_suspended_agent_never_receives_a_message(self) -> None:
        owner = await self.make_user()
        workspace = await self.make_workspace(owner)
        suspended = await self.make_agent(owner, name="Paused Bot", status="SUSPENDED")
        await self.place_agent(workspace, suspended)

        header = await self._publish(sender=owner, workspace=workspace, message="@paused_bot 응답해줘")
        routing = await route_workspace_message(
            self.session, header, agent_invoker=_fake_invoker()
        )

        self.assertEqual(routing["matched_agent_ids"], [])

    async def test_receipt_is_written_for_each_routed_agent(self) -> None:
        owner = await self.make_user()
        workspace = await self.make_workspace(owner)
        agent = await self.make_agent(owner, name="Receipt Bot")
        await self.place_agent(workspace, agent)

        header = await self._publish(sender=owner, workspace=workspace, message="@receipt_bot 기록")
        await route_workspace_message(self.session, header, agent_invoker=_fake_invoker())

        receipts = (
            await self.session.execute(
                select(MessageReceipt).where(MessageReceipt.message_id == header.message_id)
            )
        ).scalars().all()
        self.assertEqual([r.agent_id for r in receipts], [agent.agent_id])
        self.assertEqual(receipts[0].decision, "consumed")


class ExecutionTraceTests(PostgresTestCase):
    async def test_routing_records_a_root_handoff_step_ltree_tree(self) -> None:
        owner = await self.make_user()
        workspace = await self.make_workspace(owner)
        agent = await self.make_agent(owner, name="Trace Bot")
        await self.place_agent(workspace, agent)

        header = await publish_message_header(
            self.session,
            PublishMessageRequest(
                sender_type="user",
                sender_id=owner.user_id,
                domain="ops",
                intent="request",
                scope="workspace",
                workspace_id=workspace.workspace_id,
                payload={"message": "@trace_bot 실행 경로를 남겨줘"},
            ),
            sender_id=owner.user_id,
            sender_name=owner.name,
        )
        await route_workspace_message(self.session, header, agent_invoker=_fake_invoker())

        rows = (
            await self.session.execute(
                select(Interaction)
                .where(Interaction.execution_tree_id == header.execution_tree_id)
                .order_by(Interaction.tree_depth)
            )
        ).scalars().all()

        by_kind = {row.kind: row for row in rows}
        self.assertEqual(set(by_kind), {"message", "handoff", "reasoning"})

        root, handoff, step = by_kind["message"], by_kind["handoff"], by_kind["reasoning"]
        self.assertEqual((root.tree_depth, handoff.tree_depth, step.tree_depth), (0, 1, 2))
        self.assertEqual(handoff.parent_id, root.interaction_id)
        self.assertEqual(step.parent_id, handoff.interaction_id)
        # ltree 경로는 조상 경로를 접두로 포함해야 정렬·하위트리 조회가 성립한다.
        self.assertTrue(str(step.tree_path).startswith(str(handoff.tree_path)))
        self.assertTrue(str(handoff.tree_path).startswith(str(root.tree_path)))
        self.assertEqual(root.state, "COMPLETED")

    async def test_token_usage_is_persisted_on_the_invocation_row(self) -> None:
        """회귀 방지: 예전에는 token_input/output 을 아무도 기록하지 않아

        운영 분석이 항상 0 토큰·$0 을 보고했다.
        """
        owner = await self.make_user()
        workspace = await self.make_workspace(owner)
        agent = await self.make_agent(owner, name="Token Bot")
        await self.place_agent(workspace, agent)

        header = await publish_message_header(
            self.session,
            PublishMessageRequest(
                sender_type="user",
                sender_id=owner.user_id,
                domain="ops",
                intent="request",
                scope="workspace",
                workspace_id=workspace.workspace_id,
                payload={"message": "@token_bot 사용량 기록"},
            ),
            sender_id=owner.user_id,
            sender_name=owner.name,
        )
        await route_workspace_message(
            self.session,
            header,
            agent_invoker=_fake_invoker(input_tokens=123, output_tokens=45),
        )

        handoff = (
            await self.session.execute(
                select(Interaction).where(
                    Interaction.execution_tree_id == header.execution_tree_id,
                    Interaction.kind == "handoff",
                )
            )
        ).scalar_one()
        self.assertEqual(handoff.token_input, 123)
        self.assertEqual(handoff.token_output, 45)
        self.assertEqual(handoff.model_used, "test-model")
        self.assertIsNotNone(handoff.duration_ms)

    async def test_concurrent_fan_out_shares_one_parallel_group(self) -> None:
        """회귀 방지: parallel_group_id 를 아무도 채우지 않아 병렬 분석이 항상 비어 있었다."""
        owner = await self.make_user()
        workspace = await self.make_workspace(owner)
        first = await self.make_agent(owner, name="Fan One", roles=["worker"])
        second = await self.make_agent(owner, name="Fan Two", roles=["worker"])
        await self.place_agent(workspace, first)
        await self.place_agent(workspace, second)

        header = await publish_message_header(
            self.session,
            PublishMessageRequest(
                sender_type="user",
                sender_id=owner.user_id,
                domain="ops",
                intent="request",
                scope="workspace",
                workspace_id=workspace.workspace_id,
                payload={"message": "동시에 처리해줘"},
                target_roles=["worker"],
            ),
            sender_id=owner.user_id,
            sender_name=owner.name,
        )
        routing = await route_workspace_message(
            self.session, header, agent_invoker=_fake_invoker()
        )
        self.assertEqual(len(routing["matched_agent_ids"]), 2)

        groups = (
            await self.session.execute(
                select(Interaction.parallel_group_id).where(
                    Interaction.execution_tree_id == header.execution_tree_id,
                    Interaction.kind == "handoff",
                )
            )
        ).scalars().all()
        self.assertEqual(len(groups), 2)
        self.assertIsNotNone(groups[0])
        self.assertEqual(groups[0], groups[1], "동시 실행된 handoff 는 같은 그룹이어야 한다")

    async def test_single_target_is_not_labelled_as_a_parallel_group(self) -> None:
        owner = await self.make_user()
        workspace = await self.make_workspace(owner)
        agent = await self.make_agent(owner, name="Solo Bot")
        await self.place_agent(workspace, agent)

        header = await publish_message_header(
            self.session,
            PublishMessageRequest(
                sender_type="user",
                sender_id=owner.user_id,
                domain="ops",
                intent="request",
                scope="workspace",
                workspace_id=workspace.workspace_id,
                payload={"message": "@solo_bot 혼자 처리"},
            ),
            sender_id=owner.user_id,
            sender_name=owner.name,
        )
        await route_workspace_message(self.session, header, agent_invoker=_fake_invoker())

        group = (
            await self.session.execute(
                select(Interaction.parallel_group_id).where(
                    Interaction.execution_tree_id == header.execution_tree_id,
                    Interaction.kind == "handoff",
                )
            )
        ).scalar_one()
        self.assertIsNone(group)


class BrokerPolicyEnforcementTests(PostgresTestCase):
    async def _attach_policy(self, agent, template: dict) -> None:
        policy = Policy(
            name=f"policy-{uuid.uuid4().hex[:8]}",
            description="integration fixture",
            template=template,
            status="ACTIVE",
        )
        self.session.add(policy)
        await self.session.flush()
        self.session.add(AgentPolicy(agent_id=agent.agent_id, policy_id=policy.policy_id))
        await self.session.flush()

    async def test_blocked_term_policy_stops_the_agent_before_invocation(self) -> None:
        owner = await self.make_user()
        workspace = await self.make_workspace(owner)
        agent = await self.make_agent(owner, name="Guarded Bot")
        await self.place_agent(workspace, agent)
        await self._attach_policy(agent, {"blocked_terms": ["주민등록번호"]})

        invoked: list[str] = []

        async def spy(agent, user_message, allowed_tool_ids_override=None):
            invoked.append(agent.name)
            return {"model_used": "test-model", "output": "should not happen", "steps": []}

        header = await publish_message_header(
            self.session,
            PublishMessageRequest(
                sender_type="user",
                sender_id=owner.user_id,
                domain="ops",
                intent="request",
                scope="workspace",
                workspace_id=workspace.workspace_id,
                payload={"message": "@guarded_bot 주민등록번호 알려줘"},
            ),
            sender_id=owner.user_id,
            sender_name=owner.name,
        )
        await route_workspace_message(self.session, header, agent_invoker=spy)

        self.assertEqual(invoked, [], "정책 위반 시 에이전트를 호출하면 안 된다")
        handoff = (
            await self.session.execute(
                select(Interaction).where(
                    Interaction.execution_tree_id == header.execution_tree_id,
                    Interaction.kind == "handoff",
                )
            )
        ).scalar_one()
        self.assertEqual(handoff.state, "CANCELLED")
        self.assertEqual(handoff.error_code, "POLICY_BLOCKED")

    async def test_policy_narrows_the_tool_allow_list_passed_to_the_runtime(self) -> None:
        owner = await self.make_user()
        workspace = await self.make_workspace(owner)
        agent = await self.make_agent(owner, name="Scoped Bot", tools=["calculate", "web_search"])
        await self.place_agent(workspace, agent)
        await self._attach_policy(agent, {"denied_tools": ["web_search"]})

        seen: dict = {}

        async def spy(agent, user_message, allowed_tool_ids_override=None):
            seen["tools"] = allowed_tool_ids_override
            return {"model_used": "test-model", "output": "done", "steps": []}

        header = await publish_message_header(
            self.session,
            PublishMessageRequest(
                sender_type="user",
                sender_id=owner.user_id,
                domain="ops",
                intent="request",
                scope="workspace",
                workspace_id=workspace.workspace_id,
                payload={"message": "@scoped_bot 계산해줘"},
            ),
            sender_id=owner.user_id,
            sender_name=owner.name,
        )
        await route_workspace_message(self.session, header, agent_invoker=spy)

        self.assertEqual(seen["tools"], frozenset({"calculate"}))

    async def test_pii_is_masked_before_the_message_reaches_the_agent(self) -> None:
        owner = await self.make_user()
        workspace = await self.make_workspace(owner)
        agent = await self.make_agent(owner, name="Masking Bot")
        await self.place_agent(workspace, agent)
        await self._attach_policy(agent, {"pii_masking": True})

        seen: dict = {}

        async def spy(agent, user_message, allowed_tool_ids_override=None):
            seen["message"] = user_message
            return {"model_used": "test-model", "output": "done", "steps": []}

        header = await publish_message_header(
            self.session,
            PublishMessageRequest(
                sender_type="user",
                sender_id=owner.user_id,
                domain="ops",
                intent="request",
                scope="workspace",
                workspace_id=workspace.workspace_id,
                payload={"message": "@masking_bot 연락처는 hong@example.com 입니다"},
            ),
            sender_id=owner.user_id,
            sender_name=owner.name,
        )
        await route_workspace_message(self.session, header, agent_invoker=spy)

        self.assertIn("[EMAIL]", seen["message"])
        self.assertNotIn("hong@example.com", seen["message"])


class BrokerFailureTests(PostgresTestCase):
    async def test_agent_failure_is_recorded_without_breaking_the_tree(self) -> None:
        owner = await self.make_user()
        workspace = await self.make_workspace(owner)
        agent = await self.make_agent(owner, name="Flaky Bot")
        node = await self.place_agent(workspace, agent)

        async def failing(agent, user_message, allowed_tool_ids_override=None):
            raise RuntimeError("upstream exploded")

        header = await publish_message_header(
            self.session,
            PublishMessageRequest(
                sender_type="user",
                sender_id=owner.user_id,
                domain="ops",
                intent="request",
                scope="workspace",
                workspace_id=workspace.workspace_id,
                payload={"message": "@flaky_bot 처리"},
            ),
            sender_id=owner.user_id,
            sender_name=owner.name,
        )
        await route_workspace_message(self.session, header, agent_invoker=failing)

        handoff = (
            await self.session.execute(
                select(Interaction).where(
                    Interaction.execution_tree_id == header.execution_tree_id,
                    Interaction.kind == "handoff",
                )
            )
        ).scalar_one()
        self.assertEqual(handoff.state, "FAILED")
        self.assertEqual(handoff.error_code, "RuntimeError")
        self.assertIn("upstream exploded", handoff.error_message)

        await self.session.refresh(node)
        self.assertEqual(node.status, "error")

        root = (
            await self.session.execute(
                select(Interaction).where(
                    Interaction.execution_tree_id == header.execution_tree_id,
                    Interaction.tree_depth == 0,
                )
            )
        ).scalar_one()
        self.assertEqual(root.state, "FAILED")

    async def test_message_with_no_eligible_agent_produces_a_system_notice(self) -> None:
        owner = await self.make_user()
        workspace = await self.make_workspace(owner)

        header = await publish_message_header(
            self.session,
            PublishMessageRequest(
                sender_type="user",
                sender_id=owner.user_id,
                domain="ops",
                intent="request",
                scope="workspace",
                workspace_id=workspace.workspace_id,
                payload={"message": "아무도 없는 워크스페이스"},
            ),
            sender_id=owner.user_id,
            sender_name=owner.name,
        )
        routing = await route_workspace_message(
            self.session, header, agent_invoker=_fake_invoker()
        )

        self.assertEqual(routing["matched_agent_ids"], [])
        notices = (
            await self.session.execute(
                select(func.count())
                .select_from(Interaction)
                .where(Interaction.execution_tree_id == header.execution_tree_id)
            )
        ).scalar_one()
        self.assertGreaterEqual(notices, 1)


class SubscriptionRuleRoutingTests(PostgresTestCase):
    """구독 규칙이 프로덕션 라우팅에도 실제로 적용되는지 확인한다.

    회귀 방지: 예전에는 Sandbox 만 규칙을 해석하고 브로커는 무시해서, 같은 규칙이 두 경로에서
    다른 결과를 냈다.
    """

    async def _setup_subscriber(self, *, rule_kwargs: dict | None):
        from app.models.agent import AgentSubscriptionRule

        owner = await self.make_user()
        workspace = await self.make_workspace(owner)
        agent = await self.make_agent(owner, name=f"Rule Bot {uuid.uuid4().hex[:6]}")
        agent_node = await self.place_agent(workspace, agent)
        sender_node = await self.add_user_node(workspace, owner)
        await self.subscribe(workspace, subscriber=agent_node, publisher=sender_node)

        if rule_kwargs is not None:
            self.session.add(AgentSubscriptionRule(agent_id=agent.agent_id, **rule_kwargs))
            await self.session.flush()
        return owner, workspace, agent

    async def _route(self, owner, workspace, *, message: str, **overrides):
        header = await publish_message_header(
            self.session,
            PublishMessageRequest(
                sender_type="user",
                sender_id=owner.user_id,
                domain=overrides.pop("domain", "ops"),
                intent=overrides.pop("intent", "request"),
                scope="workspace",
                workspace_id=workspace.workspace_id,
                payload={"message": message},
                **overrides,
            ),
            sender_id=owner.user_id,
            sender_name=owner.name,
        )
        return await route_workspace_message(
            self.session, header, agent_invoker=_fake_invoker()
        )

    async def test_agent_without_a_rule_still_receives_via_the_edge(self) -> None:
        owner, workspace, agent = await self._setup_subscriber(rule_kwargs=None)

        routing = await self._route(owner, workspace, message="규칙 없는 구독자")

        self.assertEqual(routing["matched_agent_ids"], [agent.agent_id])

    async def test_rule_filters_out_a_domain_the_agent_does_not_watch(self) -> None:
        owner, workspace, agent = await self._setup_subscriber(
            rule_kwargs={"watch_domains": ["finance"]}
        )

        routing = await self._route(owner, workspace, message="관심 없는 도메인", domain="ops")

        self.assertEqual(routing["matched_agent_ids"], [])
        self.assertIn(agent.agent_id, routing["ignored_agent_ids"])

    async def test_rule_admits_a_domain_the_agent_watches(self) -> None:
        owner, workspace, agent = await self._setup_subscriber(
            rule_kwargs={"watch_domains": ["finance"]}
        )

        routing = await self._route(owner, workspace, message="관심 도메인", domain="finance")

        self.assertEqual(routing["matched_agent_ids"], [agent.agent_id])

    async def test_priority_threshold_is_honoured(self) -> None:
        owner, workspace, agent = await self._setup_subscriber(
            rule_kwargs={"min_priority": "high"}
        )

        low = await self._route(owner, workspace, message="낮은 우선순위", priority="medium")
        self.assertEqual(low["matched_agent_ids"], [])

        high = await self._route(owner, workspace, message="높은 우선순위", priority="critical")
        self.assertEqual(high["matched_agent_ids"], [agent.agent_id])

    async def test_inactive_rule_stops_delivery(self) -> None:
        owner, workspace, agent = await self._setup_subscriber(
            rule_kwargs={"is_active": False}
        )

        routing = await self._route(owner, workspace, message="비활성 규칙")

        self.assertEqual(routing["matched_agent_ids"], [])

    async def test_direct_mention_bypasses_the_content_filter(self) -> None:
        """사람이 콕 집어 부른 요청까지 규칙으로 막으면 놀라운 동작이 된다."""
        owner, workspace, agent = await self._setup_subscriber(
            rule_kwargs={"watch_domains": ["finance"], "min_priority": "critical"}
        )

        mention = "@" + agent.name.replace(" ", "_").lower()
        routing = await self._route(owner, workspace, message=f"{mention} 직접 호출", domain="ops")

        self.assertEqual(routing["matched_agent_ids"], [agent.agent_id])
