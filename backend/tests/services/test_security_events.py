import unittest
from unittest.mock import patch

from app.services.security_events import _deliver, _validate_url


class _Response:
    status = 202

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class SecurityEventTests(unittest.TestCase):
    def test_invalid_webhook_scheme_is_rejected(self):
        with self.assertRaises(ValueError):
            _validate_url("file:///tmp/event")

    def test_delivery_signs_json_payload(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["signature"] = request.headers.get("X-meshboard-signature")
            captured["timeout"] = timeout
            return _Response()

        with patch("app.services.security_events.urllib.request.urlopen", fake_urlopen):
            result = _deliver(
                "https://siem.example.test/events",
                "secret",
                {"event_type": "test"},
            )
        self.assertTrue(result["delivered"])
        self.assertTrue(captured["signature"].startswith("sha256="))
        self.assertGreater(captured["timeout"], 0)


if __name__ == "__main__":
    unittest.main()
