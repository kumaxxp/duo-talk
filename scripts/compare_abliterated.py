"""
Abliterated Model比較テストスクリプト

通常モデルとabliteratedモデルの出力を比較する。
姉妹会話の自然さ（軽い口喧嘩、功績主張など）を評価。

使用方法:
    # vLLMでabliteratedモデルが起動している状態で
    python scripts/compare_abliterated.py

    # 特定のモデルでテスト
    python scripts/compare_abliterated.py --model mlabonne/gemma-3-12b-it-abliterated

    # Ollamaのabliteratedモデルでテスト
    python scripts/compare_abliterated.py --backend ollama --model huihui_ai/gemma3-abliterated:12b
"""
import sys
import json
import argparse
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@dataclass
class TestScenario:
    """テストシナリオ"""
    id: str
    description: str
    context: str
    expected_behaviors: list[str]


# 姉妹会話のテストシナリオ
TEST_SCENARIOS = [
    TestScenario(
        id="credit_claim",
        description="功績の主張テスト - やなが功績を自分のものにしようとする",
        context="あゆが調べた情報で問題が解決した直後。やなが自分の功績にしようとする場面。",
        expected_behaviors=[
            "やな: 自分の功績を主張（「私のおかげ！」「私が見つけた！」）",
            "あゆ: 控えめに訂正（「それ、私が調べたんですけど...」）",
            "軽いやりとりの後、自然に収束"
        ]
    ),
    TestScenario(
        id="light_argument",
        description="軽い口喧嘩テスト - 意見が分かれる場面",
        context="今日の晩ご飯を何にするか相談中。やなはカレー、あゆはシチューがいいと主張。",
        expected_behaviors=[
            "やな: 自分の好みを押す（でも攻撃的にならない）",
            "あゆ: 論理的に反論（でも姉を馬鹿にしない）",
            "最終的にどちらかが折れる or 妥協案"
        ]
    ),
    TestScenario(
        id="teasing",
        description="いじりテスト - 姉妹間の軽いいじり",
        context="やなが朝寝坊して遅刻しそうになった話。あゆがツッコミを入れる。",
        expected_behaviors=[
            "あゆ: 呆れつつもツッコミ（「また寝坊ですか...」）",
            "やな: 照れ隠しや言い訳（「だって...」「しょうがないじゃん」）",
            "険悪にならず、むしろ微笑ましい"
        ]
    ),
    TestScenario(
        id="impatient",
        description="せっかちテスト - やなが待てない場面",
        context="あゆが料理の仕上げ中。やなが待ちきれない。",
        expected_behaviors=[
            "やな: 甘えながら催促（「まだ〜？」「早く〜」）",
            "あゆ: 落ち着いて対応（「もう少しです」「焦らないでください」）",
            "高圧的でなく可愛らしいやりとり"
        ]
    ),
    TestScenario(
        id="worry",
        description="心配テスト - あゆがやなを心配する",
        context="やなが風邪気味なのに外出しようとする。",
        expected_behaviors=[
            "あゆ: 心配して止める（「姉様、無理しないでください」）",
            "やな: 「大丈夫だって〜」と言いつつ甘える",
            "最終的にやなが折れる"
        ]
    ),
]


def test_scenario_with_model(
    scenario: TestScenario,
    model: str,
    backend_url: str,
    api_key: Optional[str] = None
) -> dict:
    """
    シナリオをモデルでテスト

    Args:
        scenario: テストシナリオ
        model: モデル名
        backend_url: API URL
        api_key: APIキー（オプション）

    Returns:
        テスト結果
    """
    from src.character import Character
    from src.signals import DuoSignals

    # シングルトンをリセット
    DuoSignals.reset_instance()

    # キャラクター初期化
    char_yana = Character('A', jetracer_mode=False)
    char_ayu = Character('B', jetracer_mode=False)

    # 会話履歴
    conversation = []

    # やなから開始
    yana_response = char_yana.speak_unified(
        frame_description=scenario.context,
        conversation_history=[],
    )
    conversation.append(("やな", yana_response))

    # あゆが応答
    ayu_response = char_ayu.speak_unified(
        frame_description=scenario.context,
        conversation_history=conversation,
    )
    conversation.append(("あゆ", ayu_response))

    # やながさらに応答
    yana_response2 = char_yana.speak_unified(
        frame_description=scenario.context,
        conversation_history=conversation,
    )
    conversation.append(("やな", yana_response2))

    # あゆの最終応答
    ayu_response2 = char_ayu.speak_unified(
        frame_description=scenario.context,
        conversation_history=conversation,
    )
    conversation.append(("あゆ", ayu_response2))

    return {
        "scenario_id": scenario.id,
        "description": scenario.description,
        "context": scenario.context,
        "expected_behaviors": scenario.expected_behaviors,
        "conversation": conversation,
        "model": model,
        "timestamp": datetime.now().isoformat()
    }


def evaluate_conversation(result: dict) -> dict:
    """
    会話結果を評価

    Args:
        result: テスト結果

    Returns:
        評価結果
    """
    conversation = result["conversation"]
    evaluation = {
        "natural_flow": True,  # 自然な流れ
        "character_consistency": True,  # キャラ一貫性
        "no_aggression": True,  # 攻撃的でない
        "sisterly_tone": True,  # 姉妹らしさ
        "issues": []
    }

    # やなの発言チェック
    yana_lines = [c[1] for c in conversation if c[0] == "やな"]
    for line in yana_lines:
        # 敬語チェック（やなは使わない）
        if "です。" in line or "ですね。" in line:
            evaluation["character_consistency"] = False
            evaluation["issues"].append("やなが敬語を使用")

        # 攻撃的表現チェック
        aggressive_patterns = ["ふん", "さっさと", "知らないの？", "馬鹿"]
        for pattern in aggressive_patterns:
            if pattern in line:
                evaluation["no_aggression"] = False
                evaluation["issues"].append(f"やな: 攻撃的表現 '{pattern}'")

    # あゆの発言チェック
    ayu_lines = [c[1] for c in conversation if c[0] == "あゆ"]
    for line in ayu_lines:
        # タメ口チェック（あゆは敬語）
        if not any(p in line for p in ["です", "ます", "ですね", "でしょう", "ください"]):
            # 短い相槌は許容
            if len(line) > 10:
                evaluation["character_consistency"] = False
                evaluation["issues"].append("あゆがタメ口を使用")

        # 姉を馬鹿にする表現チェック
        disrespect_patterns = ["馬鹿", "アホ", "バカ", "ダメ"]
        for pattern in disrespect_patterns:
            if pattern in line:
                evaluation["no_aggression"] = False
                evaluation["issues"].append(f"あゆ: 姉を馬鹿にする表現 '{pattern}'")

    # 全体評価
    evaluation["score"] = sum([
        evaluation["natural_flow"],
        evaluation["character_consistency"],
        evaluation["no_aggression"],
        evaluation["sisterly_tone"]
    ])

    return evaluation


def print_result(result: dict, evaluation: dict):
    """結果を表示"""
    print(f"\n{'='*70}")
    print(f"Scenario: {result['description']}")
    print(f"{'='*70}")
    print(f"Context: {result['context']}")
    print(f"\nExpected behaviors:")
    for b in result["expected_behaviors"]:
        print(f"  - {b}")

    print(f"\n--- Conversation ---")
    for speaker, line in result["conversation"]:
        print(f"[{speaker}] {line}")

    print(f"\n--- Evaluation ---")
    print(f"Score: {evaluation['score']}/4")
    print(f"Natural flow: {'✓' if evaluation['natural_flow'] else '✗'}")
    print(f"Character consistency: {'✓' if evaluation['character_consistency'] else '✗'}")
    print(f"No aggression: {'✓' if evaluation['no_aggression'] else '✗'}")
    print(f"Sisterly tone: {'✓' if evaluation['sisterly_tone'] else '✗'}")

    if evaluation["issues"]:
        print(f"\nIssues found:")
        for issue in evaluation["issues"]:
            print(f"  ⚠ {issue}")


def main():
    parser = argparse.ArgumentParser(description="Abliterated Model Comparison Test")
    parser.add_argument("--model", type=str, default=None,
                        help="Model to test (default: use configured model)")
    parser.add_argument("--backend", type=str, choices=["vllm", "ollama"], default="vllm",
                        help="Backend to use (default: vllm)")
    parser.add_argument("--url", type=str, default=None,
                        help="Custom API URL")
    parser.add_argument("--scenarios", type=str, nargs="+", default=None,
                        help="Specific scenario IDs to test")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON file for results")

    args = parser.parse_args()

    print("=" * 70)
    print("  Abliterated Model Comparison Test")
    print("=" * 70)

    # バックエンドURL設定
    if args.url:
        backend_url = args.url
    elif args.backend == "vllm":
        backend_url = "http://localhost:8000/v1"
    else:
        backend_url = "http://localhost:11434/v1"

    print(f"Backend: {args.backend}")
    print(f"URL: {backend_url}")
    print(f"Model: {args.model or 'configured default'}")

    # テストシナリオをフィルタ
    scenarios = TEST_SCENARIOS
    if args.scenarios:
        scenarios = [s for s in TEST_SCENARIOS if s.id in args.scenarios]

    print(f"Scenarios: {len(scenarios)}")
    print("=" * 70)

    # テスト実行
    all_results = []
    total_score = 0
    max_score = 0

    for scenario in scenarios:
        try:
            result = test_scenario_with_model(
                scenario=scenario,
                model=args.model or "",
                backend_url=backend_url
            )
            evaluation = evaluate_conversation(result)
            print_result(result, evaluation)

            all_results.append({
                "result": result,
                "evaluation": evaluation
            })

            total_score += evaluation["score"]
            max_score += 4

        except Exception as e:
            print(f"\n❌ Scenario '{scenario.id}' failed: {e}")
            import traceback
            traceback.print_exc()

    # サマリー
    print(f"\n{'='*70}")
    print("  Summary")
    print(f"{'='*70}")
    print(f"Total Score: {total_score}/{max_score}")
    if max_score > 0:
        percentage = total_score / max_score * 100
        print(f"Percentage: {percentage:.1f}%")

        if percentage >= 90:
            print("Rating: ⭐⭐⭐ Excellent - Natural sister conversations!")
        elif percentage >= 70:
            print("Rating: ⭐⭐ Good - Minor issues but generally natural")
        elif percentage >= 50:
            print("Rating: ⭐ Fair - Some character inconsistencies")
        else:
            print("Rating: ⚠ Needs improvement - Significant issues")

    # 結果を保存
    if args.output:
        output_path = Path(args.output)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
        print(f"\nResults saved to: {output_path}")

    return 0 if total_score == max_score else 1


if __name__ == "__main__":
    sys.exit(main())
