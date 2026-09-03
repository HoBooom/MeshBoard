import unittest

from app.services.schema_compat import adapt_interaction_payload


class SchemaCompatibilityTests(unittest.TestCase):
    def test_v1_record_is_adapted_to_v2(self):
        adapted = adapt_interaction_payload(
            "1.0",
            {
                "prompt": "legacy input",
                "results": "legacy output",
                "tool_name": "echo",
                "tool_input": {"message": "hello"},
                "metadata": {"legacy": True},
            },
        )
        self.assertEqual(adapted["schema_version"], "2.0")
        self.assertEqual(adapted["source_schema_version"], "1.0")
        self.assertEqual(adapted["tool"]["arguments"], {"message": "hello"})

    def test_v2_record_is_idempotently_normalized(self):
        adapted = adapt_interaction_payload(
            "2.0", {"input": "current", "output": "ok", "metadata": {}}
        )
        self.assertEqual(adapted["input"], "current")
        self.assertEqual(adapted["output"], "ok")

    def test_unknown_major_version_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError, "지원하지 않는"):
            adapt_interaction_payload("9.0", {})


if __name__ == "__main__":
    unittest.main()
