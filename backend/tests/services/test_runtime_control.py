import asyncio
import unittest
from uuid import uuid4

from app.services.runtime_control import RuntimeControlRegistry


class RuntimeControlTests(unittest.TestCase):
    def test_suspend_signals_active_execution_and_activate_resets_signal(self):
        registry = RuntimeControlRegistry()
        agent_id = uuid4()
        event = registry.begin(agent_id)
        self.assertFalse(event.is_set())
        self.assertEqual(registry.snapshot(agent_id).active_executions, 1)

        suspended = registry.suspend(agent_id)
        self.assertTrue(event.is_set())
        self.assertTrue(suspended.suspended)
        self.assertEqual(suspended.generation, 1)

        active = registry.activate(agent_id)
        self.assertFalse(active.suspended)
        self.assertEqual(active.generation, 2)
        registry.end(agent_id)
        self.assertEqual(registry.snapshot(agent_id).active_executions, 0)

    def test_suspension_event_wakes_waiter(self):
        async def verify() -> None:
            registry = RuntimeControlRegistry()
            agent_id = uuid4()
            event = registry.begin(agent_id)
            waiter = asyncio.create_task(event.wait())
            registry.suspend(agent_id)
            await asyncio.wait_for(waiter, timeout=0.1)
            registry.end(agent_id)

        asyncio.run(verify())


if __name__ == "__main__":
    unittest.main()
