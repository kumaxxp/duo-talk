"""
LLMProvider unit tests
"""
import pytest
import requests
from unittest.mock import patch, MagicMock
from src.llm_provider import (
    LLMProvider, BackendType, BackendStatus, ModelInfo,
    get_llm_provider, reset_llm_provider
)


@pytest.fixture
def provider():
    """テスト用プロバイダ"""
    reset_llm_provider()
    return LLMProvider()


class TestBackendConfig:
    def test_load_config(self, provider):
        """設定ファイル読み込み"""
        assert "backends" in provider.config
        assert "ollama" in provider.config["backends"]
        assert "vllm" in provider.config["backends"]

    def test_get_available_backends(self, provider):
        """利用可能バックエンド一覧"""
        backends = provider.get_available_backends()
        assert len(backends) >= 2

        backend_ids = [b["id"] for b in backends]
        assert "ollama" in backend_ids
        assert "vllm" in backend_ids

    def test_get_model_info_vllm(self, provider):
        """vLLMモデル情報取得"""
        info = provider.get_model_info(BackendType.VLLM, "gemma3-12b-int8")
        assert info is not None
        assert info.name == "RedHatAI/gemma-3-12b-it-quantized.w8a8"
        assert info.supports_vlm is True
        assert info.context_length == 8192

    def test_get_model_info_ollama(self, provider):
        """Ollamaモデル情報取得"""
        info = provider.get_model_info(BackendType.OLLAMA, "gemma3-12b")
        assert info is not None
        assert info.name == "gemma3:12b"
        assert info.supports_vlm is True


class TestHealthCheck:
    @patch('src.llm_provider.requests.get')
    def test_check_backend_health_success(self, mock_get, provider):
        """バックエンド接続成功"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "test-model"}]}
        mock_get.return_value = mock_response

        status = provider.check_backend_health(BackendType.VLLM)
        assert status.available is True
        assert status.current_model == "test-model"

    @patch('src.llm_provider.requests.get')
    def test_check_backend_health_failure(self, mock_get, provider):
        """バックエンド接続失敗"""
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")

        status = provider.check_backend_health(BackendType.VLLM)
        assert status.available is False
        assert status.error is not None


class TestSwitchBackend:
    @patch('src.llm_provider.requests.get')
    def test_switch_to_ollama(self, mock_get, provider):
        """Ollamaへの切り替え"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "gemma3:12b"}]}
        mock_get.return_value = mock_response

        result = provider.switch_backend(BackendType.OLLAMA, "gemma3-12b")
        assert result["success"] is True
        assert result["backend"] == "ollama"

    def test_switch_unknown_model(self, provider):
        """存在しないモデルへの切り替え"""
        result = provider.switch_backend(BackendType.VLLM, "unknown-model")
        assert result["success"] is False
        assert "Unknown model" in result["error"]


class TestDockerCommand:
    def test_get_docker_command(self, provider):
        """Docker起動コマンド生成"""
        cmd = provider.get_docker_command("gemma3-12b-int8")
        assert "docker run" in cmd
        assert "RedHatAI/gemma-3-12b-it-quantized.w8a8" in cmd
        assert "--trust-remote-code" in cmd
        assert "--max-model-len" in cmd


class TestGetClient:
    @patch('src.llm_provider.requests.get')
    def test_get_client_default(self, mock_get, provider):
        """デフォルトクライアント取得"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        client = provider.get_client()
        assert client is not None

    def test_get_model_name(self, provider):
        """モデル名取得"""
        name = provider.get_model_name()
        assert name is not None
        assert len(name) > 0


class TestSingleton:
    def test_singleton_pattern(self):
        """シングルトンパターンの確認"""
        reset_llm_provider()
        provider1 = get_llm_provider()
        provider2 = get_llm_provider()
        assert provider1 is provider2

    def test_reset_singleton(self):
        """シングルトンリセット"""
        provider1 = get_llm_provider()
        reset_llm_provider()
        provider2 = get_llm_provider()
        assert provider1 is not provider2
