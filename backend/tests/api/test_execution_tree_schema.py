import unittest
from datetime import datetime, timezone
from uuid import uuid4

from app.schemas.operations import ExecutionNodeRead, ExecutionTreeRead


class ExecutionTreeSchemaTests(unittest.TestCase):
    def test_tree_preserves_parent_and_ltree_path(self):
        tree_id, root_id, child_id = uuid4(), uuid4(), uuid4()
        now = datetime.now(timezone.utc)
        root = ExecutionNodeRead(
            interaction_id=root_id,
            execution_tree_id=tree_id,
            tree_depth=0,
            tree_path=root_id.hex,
            actor_name="사용자",
            kind="message",
            state="COMPLETED",
            start_timestamp=now,
        )
        child = ExecutionNodeRead(
            interaction_id=child_id,
            parent_id=root_id,
            execution_tree_id=tree_id,
            tree_depth=1,
            tree_path=f"{root_id.hex}.{child_id.hex}",
            actor_name="사용자",
            target_name="Agent",
            kind="handoff",
            state="COMPLETED",
            start_timestamp=now,
        )
        tree = ExecutionTreeRead(execution_tree_id=tree_id, nodes=[root, child])
        self.assertEqual(tree.nodes[1].parent_id, root_id)
        self.assertTrue(tree.nodes[1].tree_path.startswith(root_id.hex))


if __name__ == "__main__":
    unittest.main()
