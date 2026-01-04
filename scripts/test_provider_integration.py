#!/usr/bin/env python3
"""
LLMProvider統合の動作確認スクリプト
"""
import sys
sys.path.insert(0, ".")

from src.llm_provider import get_llm_provider, BackendType
from src.llm_client import get_llm_client, reset_llm_client


def main():
    print("=" * 60)
    print("LLMProvider Integration Test")
    print("=" * 60)

    # 1. プロバイダ状態確認
    print("\n[1] Provider Status")
    provider = get_llm_provider()
    status = provider.get_status()
    print(f"   Current backend: {status['current_backend']}")
    print(f"   Current model: {status['current_model']}")
    print(f"   Ollama available: {status['ollama']['available']}")
    print(f"   vLLM available: {status['vllm']['available']}")

    # 2. 利用可能バックエンド
    print("\n[2] Available Backends")
    backends = provider.get_available_backends()
    for backend in backends:
        print(f"   {backend['id']}:")
        for model in backend['models']:
            vlm_mark = "🖼️" if model['supports_vlm'] else "📝"
            print(f"      {vlm_mark} {model['id']}: {model['description']}")

    # 3. LLMClient統合確認
    print("\n[3] LLMClient Integration")
    reset_llm_client()
    client = get_llm_client(use_provider=True)
    print(f"   Client model: {client.model}")
    print(f"   Client base_url: {client.base_url}")

    client_status = client.get_provider_status()
    if client_status:
        print("   Provider status accessible: ✅")

    # 4. バックエンド切り替えテスト（接続可能な場合のみ）
    print("\n[4] Backend Switch Test")

    # Ollama確認
    ollama_status = provider.check_backend_health(BackendType.OLLAMA)
    if ollama_status.available:
        print(f"   Ollama: ✅ running ({ollama_status.current_model})")
        result = provider.switch_backend(BackendType.OLLAMA, "gemma3-12b")
        if result["success"]:
            client.refresh_from_provider()
            print(f"   Switched to Ollama: {client.model}")
    else:
        print(f"   Ollama: ❌ not available ({ollama_status.error})")

    # vLLM確認
    vllm_status = provider.check_backend_health(BackendType.VLLM)
    if vllm_status.available:
        print(f"   vLLM: ✅ running ({vllm_status.current_model})")
        result = provider.switch_backend(BackendType.VLLM, "gemma3-12b-int8")
        if result["success"]:
            client.refresh_from_provider()
            print(f"   Switched to vLLM: {client.model}")
    else:
        print(f"   vLLM: ❌ not available ({vllm_status.error})")

    # 5. Docker起動コマンド確認
    print("\n[5] Docker Commands")
    for model_id in ["gemma3-12b-int8", "gemma3-12b-gptq"]:
        cmd = provider.get_docker_command(model_id)
        print(f"\n   {model_id}:")
        print(f"   {cmd[:80]}...")

    print("\n" + "=" * 60)
    print("Integration test completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
