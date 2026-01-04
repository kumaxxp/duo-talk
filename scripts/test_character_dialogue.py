#!/usr/bin/env python3
"""
キャラクター対話テストスクリプト
やな（姉）とあゆ（妹）の対話生成
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm_provider import get_llm_provider
from src.llm_client import reset_llm_client
from src.character import Character


def main():
    print("=" * 60)
    print("Character Dialogue Test")
    print("=" * 60)

    # プロバイダ状態確認
    provider = get_llm_provider()
    status = provider.get_status()
    print(f"\nBackend: {status['current_backend']}")
    print(f"Model: {status['current_model']}")

    # LLMClient再初期化
    reset_llm_client()

    # キャラクター初期化
    print("\nLoading characters...")
    yana = Character("char_a")
    ayu = Character("char_b")
    print("[OK] Characters loaded")

    # フレーム説明
    frame_desc = "Right curve ahead, cone on right 50cm, speed 2.1 m/s, good road"

    print("\n" + "=" * 60)
    print("Frame Description:")
    print(frame_desc)

    print("=" * 60)
    print("Dialogue:")
    print("=" * 60)

    # やなの発言
    print("\n[Yana (Sister)]")
    yana_result = yana.speak_v2(
        last_utterance="",
        frame_description=frame_desc,
        dialogue_pattern="A"
    )
    yana_response = yana_result.get("content", "")
    if yana_result.get("type") == "silence":
        yana_response = "(silence)"
    print(yana_response)

    # あゆの発言
    print("\n[Ayu (Younger Sister)]")
    ayu_result = ayu.speak_v2(
        last_utterance=yana_response,
        frame_description=frame_desc,
        dialogue_pattern="B"
    )
    ayu_response = ayu_result.get("content", "")
    if ayu_result.get("type") == "silence":
        ayu_response = "(silence)"
    print(ayu_response)

    # やなの返答
    print("\n[Yana (Sister)]")
    yana_result2 = yana.speak_v2(
        last_utterance=ayu_response,
        frame_description=frame_desc,
        dialogue_pattern="C"
    )
    yana_reply = yana_result2.get("content", "")
    if yana_result2.get("type") == "silence":
        yana_reply = "(silence)"
    print(yana_reply)

    print("\n" + "=" * 60)
    print("[PASS] Character dialogue test completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
