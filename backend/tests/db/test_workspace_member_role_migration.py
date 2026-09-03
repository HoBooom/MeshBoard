from pathlib import Path
import unittest


class WorkspaceMemberRoleMigrationTests(unittest.TestCase):
    def test_role_normalization_preserves_legacy_memberships(self) -> None:
        migration = (
            Path(__file__).parents[2]
            / "alembic"
            / "versions"
            / "015_workspace_member_role_normalization.py"
        ).read_text()

        self.assertIn("SET role = 'developer' WHERE role = 'creator'", migration)
        self.assertIn("role IN ('viewer','operator','developer')", migration)
        self.assertIn('down_revision = "014_archive_immutability"', migration)
