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

    # リトライ予算: 1ターンあたりの最大リトライ回数
    MAX_RETRY_PER_TURN = 1

    # 家族設定（全シーンに共通）
    FAMILY_CONTEXT = "【前提】やなとあゆは姉妹で、同じ家に住んでいます。親戚・実家への訪問は一緒に行く前提です。"

    # トピック別の具体的なシーンヒント
    TOPIC_HINTS = {
        "お正月": "こたつで予定表を作りながら。話題候補：初詣、おみくじ、雑煮の地域差、福袋、書き初め、箱根駅伝、年賀状",
        "クリスマス": "リビングでツリーを眺めながら。話題候補：プレゼント、ケーキの種類、イルミネーション、サンタの由来",
        "花見": "桜の木の下でお弁当を広げながら。話題候補：桜の品種、場所取り、花見団子、夜桜",
        "夏祭り": "浴衣を着て屋台を歩きながら。話題候補：金魚すくい、綿あめ、花火、盆踊り、かき氷",
        "お盆": "仏壇の前で。話題候補：お墓参り、精霊馬、盆踊り、迎え火送り火、ナスとキュウリ",
        "default": "リビングで一緒に話している",
    }

    def __init__(self):
        self.vision_processor = VisionProcessor()
        self.char_a = Character("A")
        self.char_b = Character("B")
        self.director = Director()
        self.logger = Logger()

    def _generate_scene_description(self, base_scene: str) -> str:
        """
        シーン説明に家族設定と具体的なヒントを自動付与する。

        Args:
            base_scene: 基本のシーン説明

        Returns:
            家族設定とヒントを含む完全なシーン説明
        """
        # トピックに応じたヒントを選択
        hint = self.TOPIC_HINTS["default"]
        for key, value in self.TOPIC_HINTS.items():
            if key in base_scene:
                hint = value
                break

        return f"""【シーン】{base_scene}
【状況】姉妹は同じ家で、{hint}
【前提】やなとあゆは姉妹で同居。一緒に過ごす前提で会話する。
【重要】同じ話題（おせち、お年玉等）を3回以上繰り返さない。新しい視点や話題を追加する。"""

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
        guidance: Optional[str] = None,
        action: Optional[str] = None,
        hook: Optional[str] = None,
        evidence: Optional[dict] = None,
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
            "guidance": guidance,  # 次ターンへの指示
            "action": action,  # "NOOP" or "INTERVENE"
            "hook": hook,  # 介入トリガーとなる具体名詞
            "evidence": evidence,  # {"dialogue": ..., "frame": ...}
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
        print(f"📷 Topic: {scene_description or '(画像から自動生成)'}")
        if not skip_vision and image_path:
            print(f"🖼️  Image: {image_path}")
        print(f"🆔 Run ID: {run_id}")
        print(f"{'='*60}")

        # Step 1: Vision 分析（skip_vision=True の場合はスキップ）
        vision_text = None
        # シーン説明に家族設定を自動付与
        effective_scene = self._generate_scene_description(scene_description) if scene_description else None

        if skip_vision or not image_path:
            print("\n[Step 1] Skipping Vision analysis (topic-only mode)")
            result["vision_analysis"] = {"status": "skipped", "reason": "topic-only mode"}
            # トピックのみモードの場合、scene_descriptionが必須
            if not effective_scene:
                effective_scene = self._generate_scene_description("観光地を訪れている場面")
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

            # トピックが指定されていない場合、Vision分析結果からシーン説明を生成
            if not effective_scene:
                visual_info = vision_result.get("visual_info", {})
                main_subjects = visual_info.get("main_subjects", "")
                environment = visual_info.get("environment", "")

                # メイン被写体と環境からシーン説明を構築
                if main_subjects:
                    base_scene = main_subjects
                    if environment:
                        base_scene = f"{main_subjects}。{environment}"
                elif environment:
                    base_scene = environment
                else:
                    # フォールバック: raw_textの最初の部分を使用
                    raw_text = vision_result.get("raw_text", "")
                    base_scene = raw_text[:100] if raw_text else "画像に映る風景"

                # 家族設定を付与
                effective_scene = self._generate_scene_description(base_scene)
                print(f"📝 Generated scene from image: {base_scene[:50]}...")

        # Step 2: キャラクター対話生成
        # max_iterations = 対話ターン数（A→B→A→B...）
        print("\n[Step 2] Generating character dialogue...")

        dialogue_history = []
        turn_counter = 0

        # A が初手を打つ
        print(f"\n  Turn {turn_counter + 1}/{max_iterations}")
        print("    > 澄ヶ瀬やな (姉) is speaking...")
        char_a_speech = self.char_a.speak(
            frame_description=effective_scene,
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

            # 発言生成（RETRYループ対応 + Force Pass）
            retry_count = 0
            speech = None
            director_evaluation = None
            force_passed = False

            while retry_count <= self.MAX_RETRY_PER_TURN:
                print(f"    > {speaker_name} is speaking..." + (f" (retry {retry_count})" if retry_count > 0 else ""))

                # Director Guidanceを渡して発言生成
                speech = current_char.speak(
                    frame_description=effective_scene,
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
                    frame_description=effective_scene,
                    speaker=current_speaker,
                    response=speech,
                    partner_previous_speech=previous_speech,
                    speaker_domains=current_char.domains,
                    conversation_history=dialogue_history,
                )

                print(f"      [{director_evaluation.status.name}] {director_evaluation.reason}")

                # MODIFY判定: Fatal vs Non-Fatal
                if director_evaluation.status.name == "MODIFY":
                    if self.director.is_fatal_modify(director_evaluation.reason):
                        # Fatal MODIFY: 即座に停止
                        print(f"    🚨 FATAL MODIFY: {director_evaluation.reason}")
                        break
                    else:
                        # Non-Fatal MODIFY: RETRYとして扱う（降格はDirector側で実施済み）
                        print(f"    ⚠️ Non-Fatal MODIFY→RETRY扱いで続行")
                        # ステータスをRETRYに変更
                        from dataclasses import replace as dc_replace
                        from src.types import DirectorStatus
                        director_evaluation = dc_replace(director_evaluation, status=DirectorStatus.RETRY)

                # RETRY判定
                if director_evaluation.status.name == "RETRY":
                    retry_count += 1
                    if retry_count <= self.MAX_RETRY_PER_TURN:
                        # リトライ時の指示を強化（設定破壊の場合は特別な指示を追加）
                        retry_instruction = director_evaluation.suggestion
                        if "設定破壊" in (director_evaluation.reason or ""):
                            retry_instruction = f"【重要】{director_evaluation.reason}\n{director_evaluation.suggestion}\n※「あゆの家」「姉様のお家」などの表現を使わず、「うち」「私たちの家」を使ってください。"
                        print(f"    🔄 Retrying with suggestion: {retry_instruction}")
                        # 次の再生成時にDirectorの指摘を反映
                        director_guidance = retry_instruction
                        continue
                    else:
                        # リトライ上限到達: Force Pass
                        print(f"    ⚠️ リトライ上限到達: Force PASSで進行")
                        force_passed = True
                        # INTERVENEで次ターンに改善指示を出す + statusをPASSに変更
                        from dataclasses import replace as dc_replace
                        from src.types import DirectorStatus
                        director_evaluation = dc_replace(
                            director_evaluation,
                            status=DirectorStatus.PASS,  # statusをPASSに変更
                            action="INTERVENE",
                            next_instruction="前のターンの問題を踏まえて、新しい視点を追加してください。",
                        )
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

            # 次のターンへのDirector Guidanceを生成
            # v2: action=INTERVENE の場合のみ next_instruction を使用、NOOP の場合は生成しない
            next_turn_guidance = None
            if director_evaluation.action == "INTERVENE" and director_evaluation.next_instruction:
                # v2: 介入時は validate_director_output で精査された指示を使用
                next_turn_guidance = director_evaluation.next_instruction
                print(f"    🎬 Director INTERVENE: {next_turn_guidance[:50] if next_turn_guidance else '(none)'}...")
                director_guidance = next_turn_guidance
            else:
                # v2: NOOP時はguidanceを生成しない（過剰介入防止）
                director_guidance = director_evaluation.suggestion

            # GUI用 director イベントを発行（v2フィールドを含む）
            self._emit_director_event(
                run_id,
                turn_counter,
                beat,
                director_evaluation.suggestion,
                status=director_evaluation.status.name,
                reason=director_evaluation.reason,
                guidance=next_turn_guidance,
                action=director_evaluation.action,
                hook=director_evaluation.hook,
                evidence=director_evaluation.evidence,
            )

            # 最終ターンの場合のみ verdict を記録
            if turn == max_iterations - 1:
                result["director_verdict"] = {
                    "status": str(director_evaluation.status.name),
                    "reason": director_evaluation.reason,
                    "suggestion": director_evaluation.suggestion,
                }

            turn_counter += 1

            # Fatal MODIFY の場合のみ早期終了（Non-Fatal MODIFYはRETRYとして処理済み）
            if director_evaluation.status.name == "MODIFY":
                if self.director.is_fatal_modify(director_evaluation.reason):
                    print(f"\n🚨 Fatal MODIFY detected. Ending dialogue: {director_evaluation.reason}")
                    result["status"] = "error"
                    result["error"] = f"Fatal MODIFY: {director_evaluation.reason}"
                    break
                else:
                    # Non-Fatal MODIFYは続行（既にRETRY扱いされているはず）
                    print(f"\n⚠️  Non-Fatal MODIFY, continuing dialogue...")
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
