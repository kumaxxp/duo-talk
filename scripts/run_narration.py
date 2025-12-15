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

    def _emit_speak_event(
        self,
        run_id: str,
        turn: int,
        speaker: str,
        text: str,
        beat: Optional[str] = None,
    ) -> None:
        """GUI用のspeakイベントを発行"""
        from datetime import datetime
        self.logger.log_event({
            "event": "speak",
            "run_id": run_id,
            "turn": turn,
            "speaker": speaker,
            "text": text,
            "beat": beat,
            "ts": datetime.now().isoformat(),
        })

    def _emit_director_event(
        self,
        run_id: str,
        turn: int,
        beat: str,
        cut_cue: Optional[str] = None,
        status: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        """GUI用のdirectorイベントを発行"""
        from datetime import datetime
        self.logger.log_event({
            "event": "director",
            "run_id": run_id,
            "turn": turn,
            "beat": beat,
            "cut_cue": cut_cue,
            "status": status,
            "reason": reason,
            "ts": datetime.now().isoformat(),
        })

    def _emit_rag_event(
        self,
        run_id: str,
        turn: int,
        char_id: str,
        rag_hints: list,
    ) -> None:
        """GUI用のRAG選択イベントを発行"""
        from datetime import datetime

        # RAGヒントをカテゴリ別に整理
        canon_preview = ""
        lore_preview = ""
        pattern_preview = ""

        for hint in rag_hints:
            if hint.startswith("["):
                # [domain] content の形式
                bracket_end = hint.find("]")
                if bracket_end > 0:
                    domain = hint[1:bracket_end].lower()
                    content = hint[bracket_end+1:].strip()[:100]  # 最初の100文字

                    if domain in ["sake", "tourism_aesthetics", "cultural_philosophy"]:
                        canon_preview = content
                    elif domain in ["geography", "history", "architecture"]:
                        lore_preview = content
                    else:
                        pattern_preview = content

        self.logger.log_event({
            "event": "rag_select",
            "run_id": run_id,
            "turn": turn,
            "char_id": char_id,
            "canon": {"preview": canon_preview},
            "lore": {"preview": lore_preview},
            "pattern": {"preview": pattern_preview},
            "ts": datetime.now().isoformat(),
        })

    def _build_conversation_context(
        self,
        dialogue_history: list,
        max_turns: int = 3,
    ) -> Optional[str]:
        """
        直近の対話履歴から文脈を構築する。

        Args:
            dialogue_history: [(speaker, text), ...] のリスト
            max_turns: 含める最大ターン数

        Returns:
            フォーマットされた文脈文字列、または履歴がない場合はNone
        """
        if not dialogue_history:
            return None

        # 直近のmax_turns分を取得
        recent = dialogue_history[-max_turns:]

        if len(recent) <= 1:
            return None  # 直近1ターンのみの場合は文脈不要

        lines = []
        for speaker, text in recent[:-1]:  # 最後の発言は除く（partner_speechで渡されるため）
            char_name = "やな" if speaker == "A" else "あゆ"
            lines.append(f"{char_name}: {text}")

        return "\n".join(lines) if lines else None

    def process_image(
        self,
        image_path: Optional[str],
        scene_description: str,
        max_iterations: int = 2,
        run_id: Optional[str] = None,
        skip_vision: bool = False,
    ) -> dict:
        """
        画像またはトピックに対してナレーション・解説を生成する。

        Args:
            image_path: 入力画像のパス（skip_vision=True の場合は不要）
            scene_description: シーンの説明（課題テーマ）
            max_iterations: リトライの最大回数
            run_id: GUI用のランID
            skip_vision: Trueの場合、Vision分析をスキップしトピックのみで対話生成

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
        # run_id がなければ生成
        if run_id is None:
            from datetime import datetime
            run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        result = {
            "status": "processing",
            "scene_description": scene_description,
            "image_path": image_path,
            "vision_analysis": None,
            "dialogue": {},
            "director_verdict": None,
            "log_id": None,
            "run_id": run_id,
        }

        print(f"\n{'='*60}")
        print(f"📷 Topic: {scene_description}")
        if not skip_vision and image_path:
            print(f"🖼️  Image: {image_path}")
        print(f"🆔 Run ID: {run_id}")
        print(f"{'='*60}")

        # Step 1: Vision 分析（skip_vision=True の場合はスキップ）
        vision_text = None
        if skip_vision or not image_path:
            print("\n[Step 1] Skipping Vision analysis (topic-only mode)")
            result["vision_analysis"] = {"status": "skipped", "reason": "topic-only mode"}
        else:
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

        # Step 2: キャラクター対話生成
        # max_iterations = 対話ターン数（A→B→A→B...）
        print("\n[Step 2] Generating character dialogue...")

        dialogue_history = []
        turn_counter = 0

        # A が初手を打つ
        print(f"\n  Turn {turn_counter + 1}/{max_iterations}")
        print("    > 澄ヶ瀬やな (姉) is speaking...")
        char_a_speech = self.char_a.speak(
            frame_description=scene_description,
            vision_info=vision_text,
        )
        print(f"      {char_a_speech}")
        result["dialogue"][f"turn_{turn_counter}"] = {"speaker": "A", "text": char_a_speech}
        dialogue_history.append(("A", char_a_speech))
        self._emit_speak_event(run_id, turn_counter, "A", char_a_speech)
        # RAGイベントを発行
        self._emit_rag_event(run_id, turn_counter, "A", self.char_a.last_rag_hints)
        turn_counter += 1

        # Director Guidance を保持
        director_guidance = None

        # 残りのターンを交互に生成
        for turn in range(1, max_iterations):
            print(f"\n  Turn {turn + 1}/{max_iterations}")

            # 前のスピーカーを取得
            last_speaker, last_speech = dialogue_history[-1]

            # 次のスピーカーを決定（交互）
            if last_speaker == "A":
                current_speaker = "B"
                current_char = self.char_b
                speaker_name = "澄ヶ瀬あゆ (妹)"
            else:
                current_speaker = "A"
                current_char = self.char_a
                speaker_name = "澄ヶ瀬やな (姉)"

            # 対話履歴から直近の文脈を構築（最大3ターン分）
            recent_context = self._build_conversation_context(dialogue_history, max_turns=3)

            # 発言生成（RETRYループ対応）
            max_retries = 2
            retry_count = 0
            speech = None
            director_evaluation = None

            while retry_count < max_retries:
                print(f"    > {speaker_name} is speaking..." + (f" (retry {retry_count})" if retry_count > 0 else ""))

                # Director Guidanceを渡して発言生成
                speech = current_char.speak(
                    frame_description=scene_description,
                    partner_speech=last_speech,
                    director_instruction=director_guidance,
                    vision_info=vision_text,
                    conversation_context=recent_context,
                )
                print(f"      {speech}")

                # Director による品質判定
                print(f"    > Director is judging...")
                previous_speech = dialogue_history[-1][1] if len(dialogue_history) > 0 else None

                director_evaluation = self.director.evaluate_response(
                    frame_description=scene_description,
                    speaker=current_speaker,
                    response=speech,
                    partner_previous_speech=previous_speech,
                    speaker_domains=current_char.domains,
                    conversation_history=dialogue_history,
                )

                print(f"      [{director_evaluation.status.name}] {director_evaluation.reason}")

                # RETRY判定
                if director_evaluation.status.name == "RETRY":
                    retry_count += 1
                    if retry_count < max_retries:
                        print(f"    🔄 Retrying with suggestion: {director_evaluation.suggestion}")
                        # 次の再生成時にDirectorの指摘を反映
                        director_guidance = director_evaluation.suggestion
                        continue
                    else:
                        print(f"    ⚠️ Max retries reached, proceeding with current response")
                break

            # 発言を記録
            result["dialogue"][f"turn_{turn_counter}"] = {"speaker": current_speaker, "text": speech}
            dialogue_history.append((current_speaker, speech))
            self._emit_speak_event(run_id, turn_counter, current_speaker, speech)
            # RAGイベントを発行
            self._emit_rag_event(run_id, turn_counter, current_speaker, current_char.last_rag_hints)

            # beat を決定
            beat_map = {"PASS": "PAYOFF", "RETRY": "BANter", "MODIFY": "PIVOT"}
            beat = beat_map.get(director_evaluation.status.name, "BANter")

            # GUI用 director イベントを発行
            self._emit_director_event(
                run_id,
                turn_counter,
                beat,
                director_evaluation.suggestion,
                status=director_evaluation.status.name,
                reason=director_evaluation.reason,
            )

            # 次のターンへのDirector Guidanceを生成（PASSの場合）
            if director_evaluation.status.name == "PASS" and turn < max_iterations - 1:
                director_guidance = self.director.get_instruction_for_next_turn(
                    frame_description=scene_description,
                    conversation_so_far=dialogue_history,
                    turn_number=turn_counter + 1,
                )
                if director_guidance:
                    print(f"    💡 Director guidance for next turn: {director_guidance[:50]}...")
            else:
                director_guidance = director_evaluation.suggestion

            # 最終ターンの場合のみ verdict を記録
            if turn == max_iterations - 1:
                result["director_verdict"] = {
                    "status": str(director_evaluation.status.name),
                    "reason": director_evaluation.reason,
                    "suggestion": director_evaluation.suggestion,
                }

            turn_counter += 1

            # MODIFY の場合は早期終了
            if director_evaluation.status.name == "MODIFY":
                print("\n⚠️  Director requested modification. Ending dialogue.")
                result["status"] = "skip"
                break
        else:
            # ループが正常完了した場合
            print(f"\n✅ Dialogue completed ({turn_counter} turns)")
            result["status"] = "success"

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
