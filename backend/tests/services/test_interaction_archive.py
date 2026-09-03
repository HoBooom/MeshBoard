import unittest
from datetime import datetime, timezone
from uuid import uuid4

from app.models.interaction import Interaction
from app.services.interaction_archive import archive_values


class InteractionArchiveTests(unittest.TestCase):
    def test_archive_copy_is_marked_immutable_and_preserves_identity(self):
        now = datetime.now(timezone.utc)
        interaction = Interaction(
            interaction_id=uuid4(),
            conversation_id=uuid4(),
            tree_depth=0,
            actor_type="user",
            actor_id=uuid4(),
            actor_name="tester",
            kind="message",
            involved_agents=[],
            state="COMPLETED",
            complete_timestamp=now,
            metadata_={"source": "test"},
        )
        values = archive_values(interaction, now)
        self.assertEqual(values["interaction_id"], interaction.interaction_id)
        self.assertEqual(values["metadata_"], {"source": "test"})
        self.assertTrue(values["is_immutable"])
        self.assertEqual(values["archived_at"], now)


if __name__ == "__main__":
    unittest.main()
