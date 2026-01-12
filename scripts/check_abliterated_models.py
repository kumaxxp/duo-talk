"""
Abliterated Model存在確認スクリプト

HuggingFace上でabliteratedモデルの存在確認と詳細情報を取得する。

使用方法:
    python scripts/check_abliterated_models.py
"""
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from huggingface_hub import HfApi, hf_hub_download, model_info
    HF_HUB_AVAILABLE = True
except ImportError:
    HF_HUB_AVAILABLE = False
    print("Warning: huggingface_hub not installed. Install with: pip install huggingface_hub")


# チェック対象モデル
MODELS_TO_CHECK = [
    {
        "name": "mlabonne/gemma-3-12b-it-abliterated",
        "description": "Gemma 3 12B Abliterated - mlabonneのオリジナル版",
        "priority": 1,
    },
    {
        "name": "mlabonne/gemma-3-12b-it-abliterated-v2",
        "description": "Gemma 3 12B Abliterated v2 - 改良版（Minos評価使用）",
        "priority": 1,
    },
    {
        "name": "DreamFast/gemma-3-12b-it-heretic",
        "description": "Gemma 3 12B Heretic - KL divergence最小化版",
        "priority": 2,
    },
    {
        "name": "mlabonne/gemma-3-4b-it-abliterated",
        "description": "Gemma 3 4B Abliterated - 軽量版（VRAM節約）",
        "priority": 3,
    },
]


def check_model_exists(model_id: str) -> dict:
    """
    HuggingFaceでモデルの存在確認と詳細取得

    Args:
        model_id: HuggingFace model ID (e.g., "mlabonne/gemma-3-12b-it-heretic")

    Returns:
        dict with model info or error
    """
    if not HF_HUB_AVAILABLE:
        return {"exists": False, "error": "huggingface_hub not installed"}

    try:
        api = HfApi()
        info = api.model_info(model_id)

        # 基本情報抽出
        result = {
            "exists": True,
            "model_id": model_id,
            "downloads": getattr(info, "downloads", "N/A"),
            "likes": getattr(info, "likes", "N/A"),
            "created_at": str(getattr(info, "created_at", "N/A")),
            "last_modified": str(getattr(info, "last_modified", "N/A")),
            "pipeline_tag": getattr(info, "pipeline_tag", "N/A"),
            "library_name": getattr(info, "library_name", "N/A"),
            "tags": getattr(info, "tags", []),
            "gated": getattr(info, "gated", False),
            "private": getattr(info, "private", False),
        }

        # ファイルサイズ情報
        siblings = getattr(info, "siblings", [])
        if siblings:
            total_size = sum(getattr(s, "size", 0) or 0 for s in siblings)
            result["total_size_gb"] = round(total_size / (1024**3), 2)
            result["file_count"] = len(siblings)

        return result

    except Exception as e:
        return {
            "exists": False,
            "model_id": model_id,
            "error": str(e)
        }


def check_vllm_compatibility(model_id: str) -> dict:
    """
    vLLM互換性の簡易チェック

    Args:
        model_id: HuggingFace model ID

    Returns:
        dict with compatibility info
    """
    # Gemma 3系はvLLMでサポートされている
    compatibility = {
        "vllm_supported": False,
        "notes": []
    }

    model_lower = model_id.lower()

    # Gemma 3系のチェック
    if "gemma-3" in model_lower or "gemma3" in model_lower:
        compatibility["vllm_supported"] = True
        compatibility["notes"].append("Gemma 3はvLLM 0.6.0+でサポート")

    # 量子化形式のチェック
    if "gptq" in model_lower:
        compatibility["notes"].append("GPTQ量子化: vLLMでサポート")
    elif "awq" in model_lower:
        compatibility["notes"].append("AWQ量子化: vLLMでサポート")
    elif "gguf" in model_lower:
        compatibility["vllm_supported"] = False
        compatibility["notes"].append("GGUF形式: vLLMでは非サポート（llama.cpp用）")

    # INT8の場合
    if "int8" in model_lower:
        compatibility["notes"].append("INT8量子化: VRAM使用量削減")

    return compatibility


def print_model_report(model_info: dict, compat_info: dict, description: str):
    """モデルレポートを表示"""
    print(f"\n{'='*60}")
    print(f"Model: {model_info.get('model_id', 'Unknown')}")
    print(f"Description: {description}")
    print(f"{'='*60}")

    if model_info.get("exists"):
        print(f"  Status: ✅ Available")
        print(f"  Downloads: {model_info.get('downloads', 'N/A')}")
        print(f"  Likes: {model_info.get('likes', 'N/A')}")
        print(f"  Size: {model_info.get('total_size_gb', 'N/A')} GB")
        print(f"  Files: {model_info.get('file_count', 'N/A')}")
        print(f"  Library: {model_info.get('library_name', 'N/A')}")
        print(f"  Pipeline: {model_info.get('pipeline_tag', 'N/A')}")
        print(f"  Gated: {'Yes' if model_info.get('gated') else 'No'}")
        print(f"  Private: {'Yes' if model_info.get('private') else 'No'}")

        # タグ（一部）
        tags = model_info.get("tags", [])
        if tags:
            display_tags = tags[:10]
            print(f"  Tags: {', '.join(display_tags)}")
            if len(tags) > 10:
                print(f"        ... and {len(tags) - 10} more")
    else:
        print(f"  Status: ❌ Not Available")
        print(f"  Error: {model_info.get('error', 'Unknown error')}")

    # 互換性情報
    print(f"\n  vLLM Compatibility:")
    print(f"    Supported: {'✅ Yes' if compat_info.get('vllm_supported') else '❌ No'}")
    for note in compat_info.get("notes", []):
        print(f"    - {note}")


def main():
    print("=" * 70)
    print("  Abliterated Model Availability Check")
    print("=" * 70)

    if not HF_HUB_AVAILABLE:
        print("\n❌ huggingface_hub is not installed.")
        print("   Install with: pip install huggingface_hub")
        return 1

    available_models = []

    for model in MODELS_TO_CHECK:
        model_id = model["name"]
        description = model["description"]

        # モデル情報取得
        info = check_model_exists(model_id)
        compat = check_vllm_compatibility(model_id)

        # レポート表示
        print_model_report(info, compat, description)

        if info.get("exists") and compat.get("vllm_supported"):
            available_models.append({
                "model_id": model_id,
                "priority": model["priority"],
                "size_gb": info.get("total_size_gb", 0),
                "description": description
            })

    # 推奨モデルの表示
    print(f"\n{'='*70}")
    print("  Recommendation Summary")
    print(f"{'='*70}")

    if available_models:
        # 優先度順にソート
        available_models.sort(key=lambda x: (x["priority"], x["size_gb"]))

        print("\n✅ Available models for vLLM:")
        for i, m in enumerate(available_models, 1):
            print(f"  {i}. {m['model_id']}")
            print(f"     Size: {m['size_gb']} GB")
            print(f"     {m['description']}")

        best = available_models[0]
        print(f"\n🎯 Recommended: {best['model_id']}")
        print(f"   Reason: Highest priority and smallest size among available models")
    else:
        print("\n❌ No suitable models found for vLLM.")
        print("   Please check:")
        print("   1. HuggingFace access")
        print("   2. Model availability")
        print("   3. vLLM version (0.6.0+ for Gemma 3)")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
