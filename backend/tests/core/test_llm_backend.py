"""LLM 백엔드 설정 회귀 테스트.

기본 배포는 **로컬 OpenAI-호환 서버**만 사용해야 한다. 클론한 사람이 API 키 없이 실행할 수
있어야 하고, 실수로 유료 게이트웨이가 켜지는 일이 없어야 한다. 여기서는 그 계약을 고정한다.
"""

from __future__ import annotations

import unittest
import unittest.mock

from app.core.config import Settings
from app.services import agent_runtime


def _settings(**overrides) -> Settings:
    """`.env` 를 읽지 않는 격리된 Settings. 테스트가 개발자 로컬 설정에 의존하지 않게 한다."""
    return Settings(_env_file=None, **overrides)


class LocalFirstDefaultsTests(unittest.TestCase):
    def test_defaults_target_a_local_server_without_an_api_key(self) -> None:
        settings = _settings()

        self.assertFalse(settings.llm_uses_external_gateway)
        self.assertEqual(settings.llm_base_url, "http://localhost:11434/v1")
        self.assertEqual(settings.llm_default_model, "qwen2.5:7b")
        # 로컬 서버는 키를 검사하지 않지만 SDK가 빈 문자열을 거부하므로 placeholder가 있어야 한다.
        self.assertTrue(settings.llm_api_key)

    def test_default_base_url_is_loopback_so_no_paid_call_can_leave_the_machine(self) -> None:
        settings = _settings()

        self.assertRegex(settings.llm_base_url, r"^http://(localhost|127\.0\.0\.1)")

    def test_broker_timeout_exceeds_llm_timeout_so_http_errors_surface_first(self) -> None:
        settings = _settings()

        self.assertGreater(
            settings.AGENT_INVOKE_TIMEOUT_SECONDS, settings.LLM_TIMEOUT_SECONDS
        )


class GatewayOptInTests(unittest.TestCase):
    def test_filling_the_gateway_key_switches_base_url_model_and_key(self) -> None:
        settings = _settings(RUNYOUR_API_KEY="secret-key")

        self.assertTrue(settings.llm_uses_external_gateway)
        self.assertEqual(settings.llm_base_url, "https://api.runyour.ai/v1")
        self.assertEqual(settings.llm_default_model, "openai/gpt-5")
        self.assertEqual(settings.llm_api_key, "secret-key")

    def test_whitespace_only_gateway_key_stays_local(self) -> None:
        settings = _settings(RUNYOUR_API_KEY="   ")

        self.assertFalse(settings.llm_uses_external_gateway)
        self.assertEqual(settings.llm_base_url, "http://localhost:11434/v1")

    def test_any_openai_compatible_backend_can_be_swapped_in(self) -> None:
        settings = _settings(
            LLM_BASE_URL="http://localhost:8000/v1",
            LLM_MODEL="Qwen/Qwen2.5-7B-Instruct",
        )

        self.assertEqual(settings.llm_base_url, "http://localhost:8000/v1")
        self.assertEqual(settings.llm_default_model, "Qwen/Qwen2.5-7B-Instruct")


class ModelAliasTests(unittest.TestCase):
    def test_invalid_alias_json_fails_loudly(self) -> None:
        with self.assertRaises(ValueError):
            _settings(LLM_MODEL_ALIASES="not json").llm_model_aliases

    def test_non_string_alias_values_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _settings(LLM_MODEL_ALIASES='{"fast": 3}').llm_model_aliases


class ModelNameNormalizationTests(unittest.TestCase):
    """회귀 방지: 예전 구현은 "/" 없는 이름에 `openai/` 를 강제로 붙여

    Ollama 모델명(`qwen2.5:7b`)을 `openai/qwen2.5:7b` 로 망가뜨렸다.
    """

    def test_ollama_style_model_name_is_passed_through_unchanged(self) -> None:
        self.assertEqual(agent_runtime._normalize_model_name("qwen2.5:7b"), "qwen2.5:7b")

    def test_namespaced_gateway_model_name_is_passed_through_unchanged(self) -> None:
        self.assertEqual(agent_runtime._normalize_model_name("openai/gpt-5"), "openai/gpt-5")

    def test_configured_alias_is_substituted(self) -> None:
        with unittest.mock.patch.object(
            agent_runtime.settings, "LLM_MODEL_ALIASES", '{"fast": "qwen2.5:3b"}'
        ):
            self.assertEqual(agent_runtime._normalize_model_name("fast"), "qwen2.5:3b")


if __name__ == "__main__":
    unittest.main()
