#!/usr/bin/env python3
"""
Vision → Character → Director パイプライン統合スクリプト
観光地の画像・動画に対してナレーション・解説を生成し、品質判定する。
"""

import sys
import json
import re
import warnings
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.vision_processor import VisionProcessor
from src.character import Character
from src.director import Director
from src.logger import Logger
from src.owner_intervention import get_intervention_manager, InterventionState
from src.unified_pipeline import UnifiedPipeline, DialogueResult
from src.input_source import InputBundle, InputSource, SourceType


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
        self.logger = Logger()
        self.intervention_manager = get_intervention_manager()

        # UnifiedPipeline を内部で使用
        self.unified_pipeline = UnifiedPipeline(
            jetracer_client=None,  # NarrationPipelineではJetRacer不使用
            enable_fact_check=True,
        )

        # 後方互換性のため Character, Director への参照を維持
        self.char_a = self.unified_pipeline.char_a
        self.char_b = self.unified_pipeline.char_b
        self.director = self.unified_pipeline.director

        # Reset intervention state to RUNNING for new pipeline
        if self.intervention_manager.get_state() != InterventionState.RUNNING:
            print(f"[NarrationPipeline] Resetting intervention state from {self.intervention_manager.get_state().value} to RUNNING")
            self.intervention_manager.state = InterventionState.RUNNING
            self.intervention_manager.current_session = None

    def _wait_for_intervention(self, run_id: str, timeout: int = 60) -> Optional[str]:
        """
        介入状態をチェックし、一時停止中は待機する。

        Args:
            run_id: 現在のランID
            timeout: 最大待機時間（秒）。デフォルト60秒

        Returns:
            オーナー指示がある場合はその内容、なければNone
        """
        import time

        start_time = time.time()

        while True:
            # タイムアウトチェック
            elapsed = time.time() - start_time
            if elapsed > timeout:
                print(f"    ⚠️  Intervention wait timeout ({timeout}s). Force resuming...")
                # 強制的にRUNNING状態に戻す
                self.intervention_manager.state = InterventionState.RUNNING
                self.intervention_manager.current_session = None
                return None

            state = self.intervention_manager.get_state()

            if state == InterventionState.RUNNING:
                # 実行中：オーナー指示があれば取得
                instruction = self.intervention_manager.get_pending_instruction()
                if instruction:
                    # 指示をクリア（一度だけ適用）
                    self.intervention_manager.clear_pending_instruction()
                return instruction

            elif state in [InterventionState.PAUSED, InterventionState.PROCESSING,
                          InterventionState.QUERY_BACK]:
                # 一時停止中：待機
                print(f"    ⏸️  Paused by owner intervention (state: {state.value}, elapsed: {elapsed:.1f}s)")
                time.sleep(1.0)  # 1秒ごとにチェック

            elif state == InterventionState.RESUMING:
                # 再開中：指示を取得して実行再開
                instruction = self.intervention_manager.get_pending_instruction()
                if instruction:
                    self.intervention_manager.clear_pending_instruction()
                return instruction

            else:
                # 不明な状態は実行継続
                return None

    @staticmethod
    def _truncate_response(response: str, max_sentences: int = 2, max_chars: int = 100) -> str:
        """
        応答を強制的に短縮する（散漫検出の最後の手段）。

        Args:
            response: 元の応答テキスト
            max_sentences: 最大文数
            max_chars: 最大文字数

        Returns:
            短縮された応答
        """
        # 文末記号で分割（記号を保持）
        parts = re.split(r'([。！？])', response)
        result = ""
        sentence_count = 0

        # 2つずつペア（本文 + 句点）で処理
        i = 0
        while i < len(parts) - 1:
            if sentence_count >= max_sentences or len(result) > max_chars:
                break
            result += parts[i] + parts[i + 1]
            sentence_count += 1
            i += 2

        return result.strip() if result else response[:max_chars]

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
        # Director v3: Topic Manager fields
        focus_hook: Optional[str] = None,
        hook_depth: int = 0,
        depth_step: str = "DISCOVER",
        forbidden_topics: Optional[list] = None,
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
            # Director v3: Topic Manager fields
            "focus_hook": focus_hook,
            "hook_depth": hook_depth,
            "depth_step": depth_step,
            "forbidden_topics": forbidden_topics or [],
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

        @deprecated: UnifiedPipeline が内部で履歴管理するため、直接呼び出し不要。
                     後方互換性のために残しているが、新しいコードでは使用しないこと。

        Args:
            dialogue_history: [(speaker, text), ...] のリスト
            max_turns: 含める最大ターン数

        Returns:
            フォーマットされた文脈文字列、または履歴がない場合はNone
        """
        warnings.warn(
            "_build_conversation_context is deprecated. "
            "UnifiedPipeline handles conversation history internally.",
            DeprecationWarning,
            stacklevel=2
        )

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
        use_stateful_history: bool = True,  # この引数は無視（常にstateful）
    ) -> dict:
        """
        画像またはトピックに対してナレーション・解説を生成する。

        内部で UnifiedPipeline を使用するが、戻り値フォーマットは既存を維持。

        Args:
            image_path: 入力画像のパス（skip_vision=True の場合は不要）
            scene_description: シーンの説明（課題テーマ）
            max_iterations: 対話ターン数
            run_id: GUI用のランID
            skip_vision: Trueの場合、Vision分析をスキップしトピックのみで対話生成
            use_stateful_history: 後方互換性のため残すが、常にTrue扱い

        Returns:
            {
                "status": "success" | "skip" | "error",
                "scene_description": str,
                "image_path": str,
                "vision_analysis": dict,
                "dialogue": {
                    "turn_0": {"speaker": "A", "text": str},
                    "turn_1": {"speaker": "B", "text": str},
                    ...
                },
                "director_verdict": dict,
                "log_id": str (optional)
            }
        """
        # run_id がなければ生成
        if run_id is None:
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

        # Debug: Show intervention state at start
        intervention_state = self.intervention_manager.get_state()
        print(f"🔧 Intervention State: {intervention_state.value}")
        if intervention_state != InterventionState.RUNNING:
            print(f"⚠️  WARNING: Intervention state is not RUNNING, forcing reset...")
            self.intervention_manager.state = InterventionState.RUNNING
            self.intervention_manager.current_session = None

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

        # Step 2: UnifiedPipeline で対話生成
        print("\n[Step 2] Generating character dialogue with UnifiedPipeline...")

        # InputBundle を構築
        sources = [InputSource(source_type=SourceType.TEXT, content=effective_scene)]
        if image_path and not skip_vision:
            sources.append(InputSource(source_type=SourceType.IMAGE_FILE, content=image_path))

        bundle = InputBundle(sources=sources)

        # 割り込みコールバック（オーナー介入対応）
        def interrupt_callback() -> Optional[InputBundle]:
            instruction = self._wait_for_intervention(run_id)
            if instruction:
                # オーナー指示をテキスト入力として返す
                return InputBundle(
                    sources=[InputSource(source_type=SourceType.TEXT, content=instruction)],
                    is_interrupt=True,
                )
            return None

        # イベントコールバック（GUI用）
        def event_callback(event_type: str, data: dict):
            if event_type == "speak":
                self._emit_speak_event(
                    run_id,
                    data.get("turn", 0),
                    data.get("speaker", "A"),
                    data.get("text", ""),
                )
                # RAGイベント
                character = self.char_a if data.get("speaker") == "A" else self.char_b
                self._emit_rag_event(
                    run_id,
                    data.get("turn", 0),
                    data.get("speaker", "A"),
                    getattr(character, 'last_rag_hints', []) or [],
                )

        # UnifiedPipeline 実行
        pipeline_result = self.unified_pipeline.run(
            initial_input=bundle,
            max_turns=max_iterations,
            run_id=run_id,
            interrupt_callback=interrupt_callback,
            event_callback=event_callback,
        )

        # 結果を既存フォーマットに変換
        for turn in pipeline_result.dialogue:
            result["dialogue"][f"turn_{turn.turn_number}"] = {
                "speaker": turn.speaker,
                "text": turn.text,
            }

        if pipeline_result.dialogue:
            last_eval = pipeline_result.dialogue[-1].evaluation
            if last_eval:
                result["director_verdict"] = {
                    "status": str(last_eval.status.name),
                    "reason": last_eval.reason,
                    "suggestion": last_eval.suggestion,
                }

        result["status"] = pipeline_result.status
        if pipeline_result.error:
            result["error"] = pipeline_result.error

        # Step 3: ログに記録
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

        print(f"\n✅ Dialogue completed ({len(pipeline_result.dialogue)} turns)")

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
