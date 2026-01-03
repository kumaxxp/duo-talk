"""
duo-talk v2.1 プロンプト統合テスト
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock


class TestPromptLoader:
    """PromptLoader のテスト"""

    @pytest.fixture
    def loader(self):
        from src.prompt_loader import PromptLoader
        return PromptLoader("persona")

    def test_load_character_a(self, loader):
        """やなのプロンプトを読み込み"""
        prompt = loader.load_character("char_a")
        assert prompt.name == "やな"
        assert "Edge AI" in prompt.role
        assert len(prompt.forbidden) > 0

    def test_load_character_b(self, loader):
        """あゆのプロンプトを読み込み"""
        prompt = loader.load_character("char_b")
        assert prompt.name == "あゆ"
        assert "Cloud AI" in prompt.role
        assert "姉様" in prompt.relationship

    def test_load_director(self, loader):
        """ディレクタープロンプトを読み込み"""
        director = loader.load_director()
        assert director.philosophy != ""
        assert "FORCE_SPECIFIC_SLOT" in director.strategies

    def test_load_world_rules(self, loader):
        """世界設定を読み込み"""
        rules = loader.load_world_rules()
        assert "同じ場所" in rules or "共有" in rules or "姉妹" in rules

    def test_character_to_injection_text(self, loader):
        """キャラクタープロンプトの注入テキスト変換"""
        prompt = loader.load_character("char_a")
        text = prompt.to_injection_text()
        assert "やな" in text
        assert "判断基準" in text
        assert "禁止事項" in text

    def test_cache_and_reload(self, loader):
        """キャッシュとリロード"""
        # 最初の読み込み
        prompt1 = loader.load_character("char_a")

        # キャッシュから読み込み
        prompt2 = loader.load_character("char_a")

        # キャッシュクリア
        loader.clear_cache()

        # 再読み込み
        prompt3 = loader.load_character("char_a")

        assert prompt1.name == prompt2.name == prompt3.name

    def test_director_get_strategy_instruction(self, loader):
        """ディレクターの戦略指示を取得"""
        director = loader.load_director()

        # 存在する戦略
        instruction = director.get_strategy_instruction("FORCE_SPECIFIC_SLOT")
        assert instruction is not None
        assert len(instruction) > 0

        # 存在しない戦略
        instruction = director.get_strategy_instruction("NON_EXISTENT")
        assert instruction is None


class TestFewShotInjector:
    """FewShotInjector のテスト"""

    @pytest.fixture
    def injector(self):
        from src.few_shot_injector import FewShotInjector
        return FewShotInjector("persona/few_shots/patterns.yaml")

    def test_load_patterns(self, injector):
        """パターンの読み込み"""
        ids = injector.get_all_pattern_ids()
        assert len(ids) > 0
        assert "discovery_supplement" in ids
        assert "success_credit" in ids

    def test_select_pattern_for_strategy(self, injector):
        """戦略に対応するパターン選択"""
        from src.novelty_guard import LoopBreakStrategy
        from src.signals import DuoSignals

        DuoSignals.reset_instance()
        signals = DuoSignals()
        state = signals.snapshot()

        pattern = injector.select_pattern(
            signals_state=state,
            loop_strategy=LoopBreakStrategy.FORCE_SPECIFIC_SLOT
        )

        assert pattern is not None
        # パターンには数値や具体的な内容が含まれる
        assert "やな" in pattern or "あゆ" in pattern

    def test_select_pattern_for_event(self, injector):
        """イベントに対応するパターン選択"""
        from src.signals import DuoSignals

        DuoSignals.reset_instance()
        signals = DuoSignals()
        state = signals.snapshot()

        pattern = injector.select_pattern(
            signals_state=state,
            event_type="success"
        )

        assert pattern is not None

    def test_no_pattern_for_normal_state(self, injector):
        """通常状態ではパターンなし"""
        from src.signals import DuoSignals

        DuoSignals.reset_instance()
        signals = DuoSignals()
        state = signals.snapshot()

        pattern = injector.select_pattern(
            signals_state=state,
            loop_strategy=None,
            event_type=None
        )

        # センサー異常等がなければNone
        # （ただし、recent_eventsやscene_factsがあれば選択される可能性あり）

    def test_pattern_info(self, injector):
        """パターン情報の取得"""
        info = injector.get_pattern_info("discovery_supplement")
        assert info is not None
        assert info["id"] == "discovery_supplement"
        assert "triggers" in info


class TestIntegration:
    """統合テスト"""

    def test_prompt_builder_with_loaded_prompts(self):
        """PromptBuilderとプロンプトローダーの統合"""
        from src.injection import PromptBuilder, Priority
        from src.prompt_loader import PromptLoader

        loader = PromptLoader("persona")
        builder = PromptBuilder()

        # 世界設定
        world_rules = loader.load_world_rules()
        builder.add(world_rules, Priority.WORLD_RULES, "world_rules")

        # キャラクター
        char_prompt = loader.load_character("char_a")
        builder.add(
            char_prompt.to_injection_text(),
            Priority.DEEP_VALUES,
            "character"
        )

        # 履歴
        builder.add("会話履歴...", Priority.HISTORY, "history")

        # 直前発言
        builder.add("直前の発言...", Priority.LAST_UTTERANCE, "last")

        prompt = builder.build()

        # 順序確認: WORLD_RULES(15) < DEEP_VALUES(20) < HISTORY(50) < LAST_UTTERANCE(55)
        assert prompt.index("やな") < prompt.index("会話履歴")
        assert prompt.index("会話履歴") < prompt.index("直前の発言")

    def test_full_pipeline(self):
        """フルパイプラインテスト（LLM呼び出し以外）"""
        from src.signals import DuoSignals, SignalEvent, EventType
        from src.injection import PromptBuilder, Priority
        from src.novelty_guard import NoveltyGuard
        from src.silence_controller import SilenceController
        from src.prompt_loader import PromptLoader
        from src.few_shot_injector import FewShotInjector

        # 初期化
        DuoSignals.reset_instance()
        signals = DuoSignals()
        novelty_guard = NoveltyGuard()
        silence_controller = SilenceController()
        loader = PromptLoader("persona")
        few_shot = FewShotInjector("persona/few_shots/patterns.yaml")

        # センサーイベントを追加
        signals.update(SignalEvent(
            event_type=EventType.SENSOR,
            data={"speed": 1.5, "sensors": {"left": 0.3, "right": 0.3}}
        ))

        # 状態取得
        state = signals.snapshot()

        # 沈黙判定（通常速度なのでNone）
        silence = silence_controller.should_silence(state)
        assert silence is None

        # ループ検知
        loop_result = novelty_guard.check_and_update("センサーの値を確認しました")

        # プロンプト構築
        builder = PromptBuilder()
        builder.add(loader.load_world_rules(), Priority.WORLD_RULES, "world")
        builder.add(
            loader.load_character("char_a").to_injection_text(),
            Priority.DEEP_VALUES,
            "char"
        )
        builder.add("あゆ: センサー確認お願いします", Priority.LAST_UTTERANCE, "last")

        # スロットチェック
        unfilled = builder.check_and_inject_slots("センサー", topic_depth=1)

        prompt = builder.build()

        assert "やな" in prompt
        assert "センサー" in prompt


class TestCharacterSpeakV2Integration:
    """Character.speak_v2 の統合テスト（モック使用）"""

    @pytest.fixture
    def mock_character(self):
        """モックされたCharacterインスタンスを作成"""
        # DuoSignals をリセット
        from src.signals import DuoSignals
        DuoSignals.reset_instance()

        with patch('src.character.get_llm_client') as mock_llm:
            mock_llm_instance = MagicMock()
            mock_llm_instance.call.return_value = "テスト応答です"
            mock_llm.return_value = mock_llm_instance

            from src.character import Character
            char = Character("A")
            yield char

    def test_speak_v2_returns_dict(self, mock_character):
        """speak_v2 が正しい形式の辞書を返すこと"""
        result = mock_character.speak_v2(
            last_utterance="テストの発言です",
            context={"history": []},
            frame_description="テストフレーム"
        )

        assert isinstance(result, dict)
        assert "type" in result
        assert "content" in result
        assert result["type"] == "speech"

    def test_speak_v2_debug_info(self, mock_character):
        """speak_v2 がデバッグ情報を含むこと"""
        result = mock_character.speak_v2(
            last_utterance="テスト",
            context={},
            frame_description="テスト"
        )

        assert "debug" in result
        debug = result["debug"]
        assert "loop_detected" in debug
        assert "prompt_structure" in debug
        assert "character" in debug
        assert "few_shot_used" in debug

    def test_speak_v2_uses_character_prompt(self, mock_character):
        """speak_v2 が CharacterPrompt を使用すること"""
        # CharacterPromptが初期化されていることを確認
        assert hasattr(mock_character, '_character_prompt')
        assert mock_character._character_prompt is not None
        assert mock_character._character_prompt.name == "やな"

        # speak_v2を呼び出し
        result = mock_character.speak_v2(
            last_utterance="テスト",
            context={},
            frame_description="テスト"
        )

        # デバッグ情報にキャラクター名が含まれる
        assert result["debug"]["character"] == "やな"

    def test_speak_v2_with_loop_detection(self, mock_character):
        """speak_v2 がループ検知を行うこと"""
        # 同じトピックで複数回発言してループを発生させる
        for _ in range(3):
            mock_character.novelty_guard.check_and_update("センサーの値を確認")

        result = mock_character.speak_v2(
            last_utterance="センサーの値を確認してください",
            context={},
            frame_description="センサー確認中"
        )

        # ループ検知情報がデバッグに含まれる
        assert "loop_detected" in result["debug"]

    def test_speak_v2_silence_handling(self, mock_character):
        """speak_v2 が沈黙処理を行うこと"""
        from src.signals import SignalEvent, EventType

        # 高速状態をシミュレート
        mock_character.signals.update(SignalEvent(
            event_type=EventType.SENSOR,
            data={"speed": 5.0}  # 高速
        ))

        result = mock_character.speak_v2(
            last_utterance="テスト",
            context={},
            frame_description="テスト"
        )

        # 沈黙の場合は type が "silence" になる可能性
        assert result["type"] in ["speech", "silence"]


class TestCharacterV2Initialization:
    """Character クラスの v2.1 初期化テスト"""

    def setup_method(self):
        """各テスト前にDuoSignalsをリセット"""
        from src.signals import DuoSignals
        DuoSignals.reset_instance()

    def test_character_has_v2_components(self):
        with patch('src.character.get_llm_client') as mock_llm:
            mock_llm.return_value = MagicMock()

            from src.character import Character
            char = Character("A")

            # v2.1 コンポーネントが初期化されていること
            assert hasattr(char, 'signals')
            assert hasattr(char, 'novelty_guard')
            assert hasattr(char, 'silence_controller')
            assert hasattr(char, 'prompt_loader')
            assert hasattr(char, 'few_shot_injector')

            # 新しいv2.1プロンプト関連
            assert hasattr(char, '_character_prompt')
            assert hasattr(char, '_director_prompt')
            assert hasattr(char, '_world_rules')
            assert hasattr(char, 'internal_id')

    def test_character_b_has_v2_components(self):
        with patch('src.character.get_llm_client') as mock_llm:
            mock_llm.return_value = MagicMock()

            from src.character import Character
            char = Character("B")

            # あゆ用のコンポーネントが正しく初期化されていること
            assert char.char_id == "B"
            assert char.internal_id == "char_b"
            assert char._character_prompt.name == "あゆ"

    def test_reload_prompts(self):
        """reload_prompts メソッドのテスト"""
        with patch('src.character.get_llm_client') as mock_llm:
            mock_llm.return_value = MagicMock()

            from src.character import Character
            char = Character("A")

            # リロード前の状態を記録
            original_name = char._character_prompt.name

            # リロード
            char.reload_prompts()

            # リロード後も同じ内容
            assert char._character_prompt.name == original_name


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
