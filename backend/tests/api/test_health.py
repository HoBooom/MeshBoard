"""Application-level smoke tests that do not require PostgreSQL."""

import unittest

from fastapi.testclient import TestClient

from app.main import app


class HealthTests(unittest.TestCase):
    def test_health_exposes_service_version_and_environment(self) -> None:
        response = TestClient(app).get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "healthy",
                "service": "MeshBoard API",
                "version": "0.1.0",
                "environment": "development",
            },
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
