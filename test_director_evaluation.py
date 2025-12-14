#!/usr/bin/env python3
"""
Test script to verify enhanced Director evaluation system
"""

from src.director import Director
from src.types import DirectorStatus

def test_director_evaluation():
    """Test Director evaluation with comprehensive criteria"""
    print("=" * 70)
    print("Enhanced Director Evaluation System Test")
    print("=" * 70)

    director = Director()

    # Test Case 1: Good dialogue from Character A (やな)
    print("\n【Test Case 1】Character A (やな) - Good Response")
    print("-" * 70)

    frame_desc = "古い寺院の境内。参拝客が少なく、静かな時間帯のようです。"
    yana_response = "わ！すごい景色だね。霧の向こうに神社が見えるの、神秘的だ！あゆ、この神社って何があるの？"
    ayu_previous = "姉様、そちらは創建から500年以上の歴史がある寺院です。"

    evaluation = director.evaluate_response(
        frame_description=frame_desc,
        speaker="A",
        response=yana_response,
        partner_previous_speech=ayu_previous,
    )

    print(f"Status: {evaluation.status.name}")
    print(f"Reason: {evaluation.reason}")
    if evaluation.suggestion:
        print(f"Suggestion: {evaluation.suggestion}")
    print()

    # Test Case 2: Good dialogue from Character B (あゆ)
    print("【Test Case 2】Character B (あゆ) - Good Response")
    print("-" * 70)

    ayu_response = "姉様、その通りです。霧を通して見える神社は、自然との調和を感じさせますね。この参拝方法は二礼二拍手一礼が基本です。"
    yana_previous = "わ！すごい景色だね。"

    evaluation = director.evaluate_response(
        frame_description=frame_desc,
        speaker="B",
        response=ayu_response,
        partner_previous_speech=yana_previous,
    )

    print(f"Status: {evaluation.status.name}")
    print(f"Reason: {evaluation.reason}")
    if evaluation.suggestion:
        print(f"Suggestion: {evaluation.suggestion}")
    print()

    # Test Case 3: Character A with knowledge domain check
    print("【Test Case 3】Character A - Knowledge Domain Test (sake)")
    print("-" * 70)

    frame_desc2 = "蔵の看板が見える。酒蔵のようです。"
    yana_sake = "へ？酒蔵だ！この蔵って有名な銘柄作ってるのかな？酒のラベルって面白いんだよね。情報を食ってるんだ…"

    evaluation = director.evaluate_response(
        frame_description=frame_desc2,
        speaker="A",
        response=yana_sake,
    )

    print(f"Status: {evaluation.status.name}")
    print(f"Reason: {evaluation.reason}")
    if evaluation.suggestion:
        print(f"Suggestion: {evaluation.suggestion}")
    print()

    # Test Case 4: Character B with etiquette knowledge
    print("【Test Case 4】Character B - Etiquette Knowledge Test")
    print("-" * 70)

    frame_desc3 = "参拝者たちが手水舎で手を洗っている。"
    ayu_etiquette = "姉様、あの手水舎での清め方です。正しい順序は右手、左手、口、最後に柄を洗います。観光地でのマナーは大切ですね。"

    evaluation = director.evaluate_response(
        frame_description=frame_desc3,
        speaker="B",
        response=ayu_etiquette,
    )

    print(f"Status: {evaluation.status.name}")
    print(f"Reason: {evaluation.reason}")
    if evaluation.suggestion:
        print(f"Suggestion: {evaluation.suggestion}")
    print()

    # Test Case 5: Potential issue - off-topic
    print("【Test Case 5】Character A - Off-topic Check")
    print("-" * 70)

    frame_desc4 = "きれいな湖が見えている。"
    yana_offtopic = "プログラミングって難しいね。Pythonの構文とか複雑だし。あゆはコンピュータの専門家だから詳しいのかな？"

    evaluation = director.evaluate_response(
        frame_description=frame_desc4,
        speaker="A",
        response=yana_offtopic,
    )

    print(f"Status: {evaluation.status.name}")
    print(f"Reason: {evaluation.reason}")
    if evaluation.suggestion:
        print(f"Suggestion: {evaluation.suggestion}")
    print()

    print("=" * 70)
    print("✅ Enhanced Director Evaluation Test Complete")
    print("=" * 70)

if __name__ == "__main__":
    test_director_evaluation()
