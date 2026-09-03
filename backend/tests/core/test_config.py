"""Configuration validation tests for deployment safety."""

import unittest

from pydantic import ValidationError

from app.core.config import DEVELOPMENT_JWT_SECRET, Settings


class SettingsTests(unittest.TestCase):
    def test_model_pricing_normalizes_numeric_rates(self) -> None:
        config = Settings(
            _env_file=None,
            MODEL_PRICING_USD_PER_MILLION='{"test/model":{"input":1,"output":2.5}}',
        )
        self.assertEqual(config.model_pricing["test/model"]["output"], 2.5)

    def test_cors_origins_rejects_non_array_json(self) -> None:
        config = Settings(_env_file=None, CORS_ORIGINS='{"origin":"https://example.com"}')

        with self.assertRaisesRegex(ValueError, "JSON array of strings"):
            _ = config.cors_origins_list

    def test_production_rejects_default_jwt_secret(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                ENVIRONMENT="production",
                JWT_SECRET_KEY=DEVELOPMENT_JWT_SECRET,
                CORS_ORIGINS='["https://meshboard.example.com"]',
            )

    def test_production_accepts_explicit_secure_values(self) -> None:
        config = Settings(
            _env_file=None,
            ENVIRONMENT="production",
            JWT_SECRET_KEY="a-secure-production-secret-that-is-long-enough",
            CORS_ORIGINS='["https://meshboard.example.com"]',
        )

        self.assertEqual(config.ENVIRONMENT, "production")
        self.assertEqual(config.cors_origins_list, ["https://meshboard.example.com"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
