#!/usr/bin/env python3
"""
Vision → Character → Director パイプライン統合スクリプト
観光地の画像・動画に対してナレーション・解説を生成し、品質判定する。
"""

import sys
import json
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.vision_processor import VisionProcessor
from src.character import Character
from src.director import Director
from src.logger import Logger


class NarrationPipeline:
    """
    Vision分析 → キャラクター対話生成 → Director品質判定
    """

    def __init__(self):
        self.vision_processor = VisionProcessor()
        self.char_a = Character("A")
        self.char_b = Character("B")
        self.director = Director()
        self.logger = Logger()

    def process_image(
        self,
        image_path: str,
        scene_description: str,
        max_iterations: int = 2,
    ) -> dict:
        """
        単一の画像に対してナレーション・解説を生成する。

        Args:
            image_path: 入力画像のパス
            scene_description: シーンの説明（課題テーマ）
            max_iterations: リトライの最大回数

        Returns:
            {
                "status": "success" | "skip" | "error",
                "scene_description": str,
                "image_path": str,
                "vision_analysis": dict,
                "dialogue": {
                    "char_a_turn_1": str,
                    "char_b_turn_1": str,
                    "char_a_turn_2": str,
                    "char_b_turn_2": str (optional),
                    ...
                },
                "director_verdict": dict,
                "log_id": str (optional)
            }
        """
        result = {
            "status": "processing",
            "scene_description": scene_description,
            "image_path": image_path,
            "vision_analysis": None,
            "dialogue": {},
            "director_verdict": None,
            "log_id": None
        }

        print(f"\n{'='*60}")
        print(f"📷 Scene: {scene_description}")
        print(f"🖼️  Image: {image_path}")
        print(f"{'='*60}")

        # Step 1: Vision 分析
        print("\n[Step 1] Analyzing image with Vision LLM...")
        vision_result = self.vision_processor.analyze_image(image_path)

        if vision_result["status"] == "error":
            print(f"❌ Vision analysis failed: {vision_result.get('error')}")
            result["status"] = "error"
            result["vision_analysis"] = vision_result
            return result

        print("✅ Vision analysis complete")
        result["vision_analysis"] = vision_result

        # Vision 情報をキャラクター用フォーマットに変換
        vision_text = self.vision_processor.format_for_character(
            vision_result["visual_info"]
        )

        # Step 2: キャラクター対話生成（リトライロジック付き）
        print("\n[Step 2] Generating character dialogue...")

        dialogue_history = []
        for iteration in range(max_iterations):
            print(f"\n  Iteration {iteration + 1}/{max_iterations}")

            # char_a が初手を打つ
            if iteration == 0:
                print("    > 澄ヶ瀬やな (姉) is speaking...")
                char_a_speech = self.char_a.speak(
                    frame_description=scene_description,
                    vision_info=vision_text,
                )
                print(f"      {char_a_speech}")
                result["dialogue"][f"char_a_turn_{iteration + 1}"] = char_a_speech
                dialogue_history.append(("A", char_a_speech))

                # char_b が応答
                print("    > 澄ヶ瀬あゆ (妹) is speaking...")
                char_b_speech = self.char_b.speak(
                    frame_description=scene_description,
                    partner_speech=char_a_speech,
                    vision_info=vision_text,
                )
                print(f"      {char_b_speech}")
                result["dialogue"][f"char_b_turn_{iteration + 1}"] = char_b_speech
                dialogue_history.append(("B", char_b_speech))

            else:
                # 2ターン目以降（リトライ時）
                last_speaker = dialogue_history[-1][0]
                if last_speaker == "B":
                    # char_a が再度発言
                    print("    > 澄ヶ瀬やな (姉) is responding...")
                    char_a_speech = self.char_a.speak(
                        frame_description=scene_description,
                        partner_speech=dialogue_history[-1][1],
                        vision_info=vision_text,
                    )
                    print(f"      {char_a_speech}")
                    result["dialogue"][f"char_a_turn_{iteration + 1}"] = char_a_speech
                    dialogue_history.append(("A", char_a_speech))
                else:
                    # char_b が再度発言
                    print("    > 澄ヶ瀬あゆ (妹) is responding...")
                    char_b_speech = self.char_b.speak(
                        frame_description=scene_description,
                        partner_speech=dialogue_history[-1][1],
                        vision_info=vision_text,
                    )
                    print(f"      {char_b_speech}")
                    result["dialogue"][f"char_b_turn_{iteration + 1}"] = char_b_speech
                    dialogue_history.append(("B", char_b_speech))

            # Step 3: Director による品質判定
            print(f"    > Director is judging quality...")
            full_dialogue = " ".join([speech for _, speech in dialogue_history])

            director_verdict = self.director.judge(
                dialogue=full_dialogue,
                char_a_domain=self.char_a.domains,
                char_b_domain=self.char_b.domains,
            )

            result["director_verdict"] = director_verdict
            print(f"      Status: {director_verdict['status']}")
            print(f"      Reason: {director_verdict['reason']}")

            # PASS なら終了
            if director_verdict["status"] == "PASS":
                print("\n✅ Dialogue PASSED director judgment!")
                result["status"] = "success"
                break

            # MODIFY なら終了（修正指示必要）
            elif director_verdict["status"] == "MODIFY":
                print("\n⚠️  Director requested modification. Skipping.")
                result["status"] = "skip"
                break

            # RETRY なら次のイテレーションへ
            elif director_verdict["status"] == "RETRY":
                print("  ↻ Retrying with director feedback...")
                if iteration < max_iterations - 1:
                    continue
                else:
                    print("  Max iterations reached.")
                    result["status"] = "skip"
                    break

        # Step 4: ログに記録
        print("\n[Step 3] Logging to file...")
        log_id = self.logger.log_narration(
            scene_description=scene_description,
            image_path=image_path,
            vision_analysis=result["vision_analysis"],
            dialogue=result["dialogue"],
            director_verdict=result["director_verdict"],
        )
        result["log_id"] = log_id
        print(f"✅ Logged (ID: {log_id})")

        return result

    def process_batch(
        self,
        image_list: list,
        output_file: Optional[str] = None,
    ) -> list:
        """
        複数の画像を処理する。

        Args:
            image_list: [(image_path, scene_description), ...] のリスト
            output_file: 結果をJSONで出力するファイルパス（optional）

        Returns:
            結果のリスト
        """
        results = []

        for image_path, scene_description in image_list:
            result = self.process_image(
                image_path=image_path,
                scene_description=scene_description,
            )
            results.append(result)

        # 結果をファイルに保存（指定時）
        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"\n📁 Results saved to: {output_file}")

        return results


def main():
    """
    スクリプト実行例
    """
    pipeline = NarrationPipeline()

    # テスト用の画像リスト
    test_images = [
        ("tests/images/temple_sample.jpg", "古い寺院の境内。参拝客が少なく、静かな時間帯のようです。"),
        ("tests/images/nature_sample.jpg", "緑豊かな山間の風景。自然に包まれた観光地です。"),
    ]

    if not test_images:
        print("No test images provided.")
        print("Usage: python scripts/run_narration.py")
        print("\nTo test:")
        print("1. 画像ファイルをローカルに配置")
        print("2. 以下をコード内で設定：")
        print('   test_images = [("path/to/image.jpg", "シーン説明"), ...]')
        print("3. スクリプトを実行")
        return

    results = pipeline.process_batch(
        image_list=test_images,
        output_file="runs/narration_results.json",
    )

    print("\n" + "="*60)
    print(f"✅ Processing complete! ({len([r for r in results if r['status'] == 'success'])} / {len(results)} passed)")
    print("="*60)


if __name__ == "__main__":
    main()
