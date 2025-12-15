#!/usr/bin/env python3
"""
ファクトチェック機能のテスト
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fact_checker import FactChecker, get_fact_checker


def test_strong_zero():
    """ストロングゼロの誤認識をテスト"""
    print("=" * 60)
    print("テスト1: ストロングゼロの誤認識")
    print("=" * 60)

    checker = get_fact_checker()

    # やなの誤った発言
    statement = "ストロングゼロかぁ、呑みたいんだね。あゆ、それって甘くて美味しいの？ ちょっと呑んでみたいな、どんな味？ あ、でもノンアルか。"

    print(f"\n【検証する発言】\n{statement}\n")

    result = checker.check_statement(statement)

    print(f"\n【結果】")
    print(f"  誤り検出: {result.has_error}")
    print(f"  検出した主張: {result.claim}")
    print(f"  正しい情報: {result.correct_info}")
    print(f"  確信度: {result.search_confidence}")

    if result.correction_prompt:
        print(f"\n【訂正プロンプト】\n{result.correction_prompt}")

    return result.has_error


def test_correct_statement():
    """正しい発言のテスト"""
    print("\n" + "=" * 60)
    print("テスト2: 正しい発言（誤りなし）")
    print("=" * 60)

    checker = get_fact_checker()

    # 正しい発言
    statement = "わ、金閣寺だね！金色できれいだなぁ。"

    print(f"\n【検証する発言】\n{statement}\n")

    result = checker.check_statement(statement)

    print(f"\n【結果】")
    print(f"  誤り検出: {result.has_error}")
    print(f"  確信度: {result.search_confidence}")

    return not result.has_error  # 誤りがないのが正しい


def test_opinion_skip():
    """意見・感想はスキップするテスト"""
    print("\n" + "=" * 60)
    print("テスト3: 意見・感想（スキップ）")
    print("=" * 60)

    checker = get_fact_checker()

    # 感想のみの発言
    statement = "美味しそうだね！私も食べたいな。"

    print(f"\n【検証する発言】\n{statement}\n")

    result = checker.check_statement(statement)

    print(f"\n【結果】")
    print(f"  誤り検出: {result.has_error}")
    print(f"  確信度: {result.search_confidence}")

    return not result.has_error


if __name__ == "__main__":
    print("\n🔍 ファクトチェック機能テスト\n")

    results = []

    try:
        results.append(("ストロングゼロ誤認識", test_strong_zero()))
    except Exception as e:
        print(f"❌ テスト1 エラー: {e}")
        results.append(("ストロングゼロ誤認識", False))

    try:
        results.append(("正しい発言", test_correct_statement()))
    except Exception as e:
        print(f"❌ テスト2 エラー: {e}")
        results.append(("正しい発言", False))

    try:
        results.append(("意見スキップ", test_opinion_skip()))
    except Exception as e:
        print(f"❌ テスト3 エラー: {e}")
        results.append(("意見スキップ", False))

    print("\n" + "=" * 60)
    print("テスト結果サマリー")
    print("=" * 60)
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {name}")
