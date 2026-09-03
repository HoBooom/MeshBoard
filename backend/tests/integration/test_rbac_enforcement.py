"""인증·권한 강제 통합 테스트.

`RequireRoles` 와 객체 단위 인가(소유권·워크스페이스 멤버십·발신자 위조 차단)는
실제 요청이 전체 의존성 체인(JWT 디코드 → DB 사용자 조회 → 역할 검사)을 통과해야만
검증된다. 그래서 앱을 ASGI 로 직접 태우고 실제 DB 세션을 주입한다.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.core.security import create_access_token, create_refresh_token
from app.db.session import get_db
from app.main import app

from ._harness import PostgresTestCase


class ApiTestCase(PostgresTestCase):
    """테스트 트랜잭션에 묶인 세션을 앱에 주입하는 케이스."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()

        async def _override():
            # 요청이 끝나도 세션을 닫지 않는다. 바깥 트랜잭션은 teardown 에서 롤백한다.
            yield self.session

        app.dependency_overrides[get_db] = _override
        self.client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        app.dependency_overrides.pop(get_db, None)
        await super().asyncTearDown()

    def auth(self, user) -> dict[str, str]:
        token = create_access_token({"sub": str(user.user_id)})
        return {"Authorization": f"Bearer {token}"}


class AuthenticationTests(ApiTestCase):
    async def test_request_without_a_token_is_rejected(self) -> None:
        response = await self.client.get("/api/v1/trust/policies")
        self.assertEqual(response.status_code, 401)

    async def test_garbage_token_is_rejected(self) -> None:
        response = await self.client.get(
            "/api/v1/trust/policies", headers={"Authorization": "Bearer not-a-jwt"}
        )
        self.assertEqual(response.status_code, 401)

    async def test_refresh_token_cannot_be_used_as_an_access_token(self) -> None:
        user = await self.make_user()
        refresh = create_refresh_token({"sub": str(user.user_id)})

        response = await self.client.get(
            "/api/v1/trust/policies", headers={"Authorization": f"Bearer {refresh}"}
        )
        self.assertEqual(response.status_code, 401)

    async def test_token_for_a_deleted_user_is_rejected(self) -> None:
        token = create_access_token({"sub": "00000000-0000-0000-0000-000000000000"})

        response = await self.client.get(
            "/api/v1/trust/policies", headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(response.status_code, 401)

    async def test_suspended_account_is_refused_even_with_a_valid_token(self) -> None:
        user = await self.make_user(state="SUSPENDED")

        response = await self.client.get("/api/v1/trust/policies", headers=self.auth(user))
        self.assertEqual(response.status_code, 403)


class RoleGateTests(ApiTestCase):
    """`RequireRoles` 가 실제로 쓰기 작업을 막는지 확인한다."""

    _POLICY = {"name": "integration policy", "template": {"pii_masking": True}}

    async def test_role_without_trust_write_cannot_create_a_policy(self) -> None:
        user = await self.make_user(roles=["agent_owner"])

        response = await self.client.post(
            "/api/v1/trust/policies", json=self._POLICY, headers=self.auth(user)
        )
        self.assertEqual(response.status_code, 403)

    async def test_user_with_no_role_at_all_cannot_create_a_policy(self) -> None:
        user = await self.make_user()

        response = await self.client.post(
            "/api/v1/trust/policies", json=self._POLICY, headers=self.auth(user)
        )
        self.assertEqual(response.status_code, 403)

    async def test_governance_role_can_create_a_policy(self) -> None:
        user = await self.make_user(roles=["governance"])

        response = await self.client.post(
            "/api/v1/trust/policies", json=self._POLICY, headers=self.auth(user)
        )
        self.assertEqual(response.status_code, 201, response.text)

    async def test_reads_stay_open_to_any_authenticated_user(self) -> None:
        user = await self.make_user()

        response = await self.client.get("/api/v1/trust/policies", headers=self.auth(user))
        self.assertEqual(response.status_code, 200)

    async def test_operations_write_requires_an_operations_role(self) -> None:
        owner = await self.make_user()
        outsider = await self.make_user(roles=["agent_owner"])
        agent = await self.make_agent(owner)

        response = await self.client.patch(
            f"/api/v1/operations/agents/{agent.agent_id}/status",
            json={"status": "SUSPENDED"},
            headers=self.auth(outsider),
        )
        self.assertEqual(response.status_code, 403)


class ObjectLevelAuthorizationTests(ApiTestCase):
    """역할과 별개로, 남의 리소스에 접근할 수 없어야 한다."""

    async def test_private_agent_is_hidden_from_other_users(self) -> None:
        owner = await self.make_user()
        stranger = await self.make_user()
        agent = await self.make_agent(owner, visibility="PRIVATE")

        response = await self.client.get(
            f"/api/v1/agents/{agent.agent_id}", headers=self.auth(stranger)
        )
        self.assertEqual(response.status_code, 403)

    async def test_public_agent_is_readable_by_other_users(self) -> None:
        owner = await self.make_user()
        stranger = await self.make_user()
        agent = await self.make_agent(owner, visibility="PUBLIC")

        response = await self.client.get(
            f"/api/v1/agents/{agent.agent_id}", headers=self.auth(stranger)
        )
        self.assertEqual(response.status_code, 200, response.text)

    async def test_agent_listing_only_returns_agents_you_own(self) -> None:
        owner = await self.make_user()
        stranger = await self.make_user()
        mine = await self.make_agent(owner)
        theirs = await self.make_agent(stranger, visibility="PUBLIC")

        response = await self.client.get("/api/v1/agents", headers=self.auth(owner))
        self.assertEqual(response.status_code, 200)
        returned = {item["agent_id"] for item in response.json()}
        self.assertIn(str(mine.agent_id), returned)
        self.assertNotIn(str(theirs.agent_id), returned)

    async def test_non_member_cannot_read_a_workspace(self) -> None:
        owner = await self.make_user()
        stranger = await self.make_user()
        workspace = await self.make_workspace(owner)

        response = await self.client.get(
            f"/api/v1/workspaces/{workspace.workspace_id}", headers=self.auth(stranger)
        )
        self.assertEqual(response.status_code, 403)

    async def test_only_a_privileged_role_can_create_a_workspace(self) -> None:
        plain = await self.make_user()

        response = await self.client.post(
            "/api/v1/workspaces",
            json={"name": "blocked", "agent_placements": []},
            headers=self.auth(plain),
        )
        self.assertEqual(response.status_code, 403)


class SenderSpoofingTests(ApiTestCase):
    """메시지 발행은 발신자를 위조할 수 없어야 한다."""

    def _payload(self, **overrides) -> dict:
        base = {
            "sender_type": "user",
            "domain": "ops",
            "intent": "request",
            "scope": "workspace",
            "payload": {"message": "안녕하세요"},
        }
        base.update(overrides)
        return base

    async def test_cannot_publish_as_another_user(self) -> None:
        owner = await self.make_user()
        attacker = await self.make_user()
        workspace = await self.make_workspace(owner)
        # 공격자를 멤버로 넣어 워크스페이스 접근 자체는 통과시키고, 발신자 위조만 남긴다.
        from app.models.workspace import WorkspaceMember

        self.session.add(
            WorkspaceMember(
                workspace_id=workspace.workspace_id,
                user_id=attacker.user_id,
                role="viewer",
                granted_by=owner.user_id,
            )
        )
        await self.session.flush()

        response = await self.client.post(
            "/api/v1/messages/publish",
            json=self._payload(
                sender_id=str(owner.user_id), workspace_id=str(workspace.workspace_id)
            ),
            headers=self.auth(attacker),
        )
        self.assertEqual(response.status_code, 403)

    async def test_cannot_publish_as_an_agent_you_do_not_own(self) -> None:
        owner = await self.make_user()
        attacker = await self.make_user()
        workspace = await self.make_workspace(attacker)
        agent = await self.make_agent(owner)

        response = await self.client.post(
            "/api/v1/messages/publish",
            json=self._payload(
                sender_type="agent",
                sender_id=str(agent.agent_id),
                workspace_id=str(workspace.workspace_id),
            ),
            headers=self.auth(attacker),
        )
        self.assertEqual(response.status_code, 403)

    async def test_non_member_cannot_publish_into_a_workspace(self) -> None:
        owner = await self.make_user()
        stranger = await self.make_user()
        workspace = await self.make_workspace(owner)

        response = await self.client.post(
            "/api/v1/messages/publish",
            json=self._payload(
                sender_id=str(stranger.user_id), workspace_id=str(workspace.workspace_id)
            ),
            headers=self.auth(stranger),
        )
        self.assertEqual(response.status_code, 403)
