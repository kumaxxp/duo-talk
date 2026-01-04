"""
LLMClient + LLMProvider integration tests
"""
import pytest
from unittest.mock import patch, MagicMock

from src.llm_client import LLMClient, get_llm_client, reset_llm_client
from src.llm_provider import reset_llm_provider, BackendType


@pytest.fixture(autouse=True)
def reset_singletons():
    """テスト前後でシングルトンをリセット"""
    reset_llm_client()
    reset_llm_provider()
    yield
    reset_llm_client()
    reset_llm_provider()


class TestLLMClientWithProvider:
    def test_init_with_provider(self):
        """LLMProvider経由での初期化"""
        client = LLMClient(use_provider=True)
        assert client._use_provider is True
        assert client._provider is not None
        assert client.model is not None

    def test_init_without_provider(self):
        """従来方式での初期化（後方互換）"""
        client = LLMClient(
            use_provider=False,
            base_url="http://localhost:11434/v1",
            model="test-model"
        )
        assert client._use_provider is False
        assert client._provider is None
        assert client.model == "test-model"

    def test_get_provider_status(self):
        """プロバイダ状態取得"""
        client = LLMClient(use_provider=True)
        status = client.get_provider_status()
        assert status is not None
        assert "ollama" in status
        assert "vllm" in status

    @patch('src.llm_provider.requests.get')
    def test_refresh_from_provider(self, mock_get):
        """プロバイダからの再取得"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "test"}]}
        mock_get.return_value = mock_response

        client = LLMClient(use_provider=True)

        # 切り替え後にrefresh
        client._provider.switch_backend(BackendType.OLLAMA, "gemma3-12b")
        client.refresh_from_provider()

        # モデル名が更新されていることを確認
        assert client.model is not None


class TestGlobalClient:
    def test_get_llm_client_singleton(self):
        """シングルトン動作確認"""
        client1 = get_llm_client()
        client2 = get_llm_client()
        assert client1 is client2

    def test_reset_llm_client(self):
        """リセット動作確認"""
        client1 = get_llm_client()
        reset_llm_client()
        client2 = get_llm_client()
        assert client1 is not client2


class TestProviderStatusFromClient:
    def test_provider_status_contents(self):
        """プロバイダ状態の内容確認"""
        client = LLMClient(use_provider=True)
        status = client.get_provider_status()

        assert "current_backend" in status
        assert "current_model" in status
        assert "ollama" in status
        assert "vllm" in status
        assert "defaults" in status

    def test_no_provider_status_without_provider(self):
        """プロバイダ未使用時はNone"""
        client = LLMClient(use_provider=False)
        status = client.get_provider_status()
        assert status is None
