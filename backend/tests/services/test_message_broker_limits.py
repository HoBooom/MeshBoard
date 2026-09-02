"""Message broker invocation safeguards."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.message_broker import _invoke_routed_agent


class MessageBrokerLimitTests(unittest.TestCase):
    def test_invocation_timeout_is_enforced(self) -> None:
        async def slow_invoker(**_: object) -> dict:
            await asyncio.sleep(0.05)
            return {"output": "late"}

        async def run() -> None:
            with patch("app.services.message_broker.settings.AGENT_INVOKE_TIMEOUT_SECONDS", 0.001):
                with self.assertRaises(asyncio.TimeoutError):
                    await _invoke_routed_agent(
                        slow_invoker,
                        SimpleNamespace(agent_id="test"),
                        "hello",
                        asyncio.Semaphore(1),
                    )

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main(verbosity=2)
