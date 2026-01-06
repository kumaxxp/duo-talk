"""Character モード切り替えテスト"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from src.character import Character


class TestCharacterMode:
    """Characterのモード切り替えテスト"""

    def test_character_jetracer_mode_attribute(self):
        """jetracer_mode属性が正しく設定されることを確認"""
        char_general = Character("A", jetracer_mode=False)
        char_jetracer = Character("A", jetracer_mode=True)

        assert char_general.jetracer_mode is False
        assert char_jetracer.jetracer_mode is True

    def test_tone_reminder_jetracer_mode(self):
        """JetRacerモードの口調リマインダー"""
        char = Character("A", jetracer_mode=True)
        reminder = char._get_tone_reminder()
        reminder_text = "\n".join(reminder)

        # JetRacer特有の文言があることを確認
        assert "エッジAI" in reminder_text or "センサー" in reminder_text or "JetRacer" in reminder_text

    def test_tone_reminder_general_mode(self):
        """一般会話モードの口調リマインダー"""
        char = Character("A", jetracer_mode=False)
        reminder = char._get_tone_reminder()
        reminder_text = "\n".join(reminder)

        # JetRacer特有の文言がないことを確認
        assert "エッジAI" not in reminder_text
        # 一般会話の特徴があることを確認
        assert "発見者" in reminder_text or "好奇心" in reminder_text or "直感" in reminder_text

    def test_char_b_tone_reminder_modes(self):
        """あゆの口調リマインダーモード切り替え"""
        char_general = Character("B", jetracer_mode=False)
        char_jetracer = Character("B", jetracer_mode=True)

        general_reminder = "\n".join(char_general._get_tone_reminder())
        jetracer_reminder = "\n".join(char_jetracer._get_tone_reminder())

        # 一般会話モード
        assert "解説者" in general_reminder or "論理" in general_reminder or "知識" in general_reminder
        assert "クラウドAI" not in general_reminder

        # JetRacerモード
        assert "クラウドAI" in jetracer_reminder or "データ" in jetracer_reminder or "分析" in jetracer_reminder

    def test_default_mode_is_general(self):
        """デフォルトモードが一般会話であることを確認（UnifiedPipelineが入力に応じてモード決定）"""
        char = Character("A")  # jetracer_modeを指定しない
        assert char.jetracer_mode is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
