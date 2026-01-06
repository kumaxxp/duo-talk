"""PromptManager モード切り替えテスト"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from src.prompt_manager import PromptManager, get_prompt_manager, get_prompt_repository


class TestPromptManagerMode:
    """PromptManagerのモード切り替えテスト"""

    def setup_method(self):
        """各テスト前にキャッシュをクリア"""
        repo = get_prompt_repository()
        if hasattr(repo, 'clear_cache'):
            repo.clear_cache()

    def test_general_mode_loads_general_prompt(self):
        """一般会話モードでsystem_general.txtが読み込まれることを確認"""
        pm = PromptManager("A", jetracer_mode=False)
        # JetRacer特有の文言がないことを確認
        assert "エッジAI" not in pm.fixed
        # 一般会話の特徴的な文言があることを確認
        assert "発見者" in pm.fixed or "直感" in pm.fixed or "好奇心" in pm.fixed

    def test_jetracer_mode_loads_jetracer_prompt(self):
        """JetRacerモードでsystem_jetracer.txtが読み込まれることを確認"""
        pm = PromptManager("A", jetracer_mode=True)
        # JetRacer特有の文言があることを確認
        assert "エッジAI" in pm.fixed or "Jetson" in pm.fixed or "センサー" in pm.fixed

    def test_char_b_general_mode(self):
        """あゆの一般会話モード"""
        pm = PromptManager("B", jetracer_mode=False)
        # JetRacer特有の文言がないことを確認
        assert "クラウドAI" not in pm.fixed
        # 一般会話の特徴的な文言があることを確認
        assert "解説者" in pm.fixed or "論理" in pm.fixed or "知識" in pm.fixed

    def test_char_b_jetracer_mode(self):
        """あゆのJetRacerモード"""
        pm = PromptManager("B", jetracer_mode=True)
        # JetRacer特有の文言があることを確認
        assert "クラウドAI" in pm.fixed or "分析" in pm.fixed or "データ" in pm.fixed

    def test_cache_separation_by_mode(self):
        """モードごとにキャッシュが分離されていることを確認"""
        pm_general = get_prompt_manager("A", jetracer_mode=False)
        pm_jetracer = get_prompt_manager("A", jetracer_mode=True)
        assert pm_general.fixed != pm_jetracer.fixed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
