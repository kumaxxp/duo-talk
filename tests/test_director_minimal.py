"""
DirectorMinimal のユニットテスト

最小構成ディレクターの静的チェック機能をテスト
"""

import pytest
from src.director_minimal import DirectorMinimal, get_director_minimal
from src.types import DirectorStatus


class TestDirectorMinimal:
    """DirectorMinimal の基本テスト"""

    def setup_method(self):
        """各テストの前に新しいインスタンスを作成"""
        self.director = DirectorMinimal()

    def test_pass_correct_tone_a(self):
        """やな（A）の正しい口調はPASS"""
        result = self.director.evaluate_response(
            frame_description="テスト",
            speaker="A",
            response="わ！すごいね！",  # 短く、感情的
            turn_number=1,
            frame_num=1,
        )
        assert result.status == DirectorStatus.PASS

    def test_pass_correct_tone_b(self):
        """あゆ（B）の正しい口調はPASS"""
        result = self.director.evaluate_response(
            frame_description="テスト",
            speaker="B",
            response="これは興味深い現象ですね。一般的にはこのような仕組みになっています。",
            turn_number=1,
            frame_num=1,
        )
        assert result.status == DirectorStatus.PASS

    def test_retry_a_uses_sister_honorific(self):
        """やな（A）が「姉様」を使うとRETRY"""
        result = self.director.evaluate_response(
            frame_description="テスト",
            speaker="A",
            response="姉様、すごいですね。",
            turn_number=1,
            frame_num=1,
        )
        assert result.status == DirectorStatus.RETRY
        assert "姉様" in result.reason

    def test_retry_b_praise_with_recipient(self):
        """あゆ（B）が相手への褒め言葉を使うとRETRY"""
        result = self.director.evaluate_response(
            frame_description="テスト",
            speaker="B",
            response="あなたの答えはさすがですね。",
            turn_number=1,
            frame_num=1,
        )
        assert result.status == DirectorStatus.RETRY
        assert "褒め言葉" in result.reason or "さすが" in result.reason

    def test_warn_b_praise_without_recipient(self):
        """あゆ（B）が褒め言葉を使う（相手なし）とWARN"""
        result = self.director.evaluate_response(
            frame_description="テスト",
            speaker="B",
            response="さすがの技術ですね。素晴らしい設計です。",
            turn_number=1,
            frame_num=1,
        )
        assert result.status in [DirectorStatus.WARN, DirectorStatus.RETRY]

    def test_pass_a_praise_ok(self):
        """やな（A）は褒め言葉を使ってもOK"""
        result = self.director.evaluate_response(
            frame_description="テスト",
            speaker="A",
            response="さすがだね！すごいじゃん！",
            turn_number=1,
            frame_num=1,
        )
        # やなには褒め言葉制限が適用されない
        assert result.status != DirectorStatus.RETRY or "褒め言葉" not in result.reason

    def test_retry_separation_words(self):
        """別居を示唆する表現はRETRY"""
        result = self.director.evaluate_response(
            frame_description="テスト",
            speaker="A",
            response="じゃあ、また来てね！",
            turn_number=1,
            frame_num=1,
        )
        assert result.status == DirectorStatus.RETRY
        assert "設定破壊" in result.reason

    def test_retry_too_long_response(self):
        """長すぎる応答（8行以上）はRETRY"""
        # 口調マーカーを含めつつ、長すぎる応答
        long_response = "わ！すごいね！\n" + "\n".join([f"行{i}の内容だね！" for i in range(10)])
        result = self.director.evaluate_response(
            frame_description="テスト",
            speaker="A",
            response=long_response,
            turn_number=1,
            frame_num=1,
        )
        assert result.status == DirectorStatus.RETRY
        assert "複数行" in result.reason

    def test_warn_medium_response(self):
        """中程度の長さの応答（6-7行）はWARN"""
        medium_response = "\n".join([f"行{i}の内容です。" for i in range(6)])
        result = self.director.evaluate_response(
            frame_description="テスト",
            speaker="A",
            response=medium_response,
            turn_number=1,
            frame_num=1,
        )
        # 口調が不足しているのでRETRYまたはWARN
        assert result.status in [DirectorStatus.WARN, DirectorStatus.RETRY]

    def test_commit_evaluation_noop(self):
        """commit_evaluation は何もしない（互換性のため）"""
        result = self.director.evaluate_response(
            frame_description="テスト",
            speaker="A",
            response="わ！すごいね！",
            turn_number=1,
            frame_num=1,
        )
        # エラーが発生しないことを確認
        self.director.commit_evaluation("わ！すごいね！", result)

    def test_reset_methods_noop(self):
        """リセットメソッドは何もしない（互換性のため）"""
        # エラーが発生しないことを確認
        self.director.reset_for_new_session()
        self.director.reset_topic_state()


class TestDirectorMinimalSingleton:
    """get_director_minimal のシングルトン動作テスト"""

    def test_singleton_same_instance(self):
        """同じインスタンスが返される"""
        d1 = get_director_minimal()
        d2 = get_director_minimal()
        assert d1 is d2


class TestDirectorMinimalToneMarkers:
    """口調マーカーの詳細テスト"""

    def setup_method(self):
        self.director = DirectorMinimal()

    def test_a_markers_detection(self):
        """やな（A）の口調マーカー検出"""
        # マーカーあり
        result = self.director._check_tone_markers("A", "わ！これすごいね！")
        assert result["status"] == DirectorStatus.PASS
        assert result["score"] >= 2

    def test_a_missing_markers(self):
        """やな（A）のマーカー不足"""
        result = self.director._check_tone_markers("A", "これは興味深い現象です。")
        assert result["status"] in [DirectorStatus.WARN, DirectorStatus.RETRY]
        assert result["score"] < 2

    def test_b_markers_detection(self):
        """あゆ（B）の口調マーカー検出"""
        result = self.director._check_tone_markers("B", "これは興味深いですね。一般的にはそうなります。")
        assert result["status"] == DirectorStatus.PASS
        assert result["score"] >= 2

    def test_b_missing_markers(self):
        """あゆ（B）のマーカー不足"""
        result = self.director._check_tone_markers("B", "すごいね！面白いかも！")
        assert result["status"] in [DirectorStatus.WARN, DirectorStatus.RETRY]
        assert result["score"] < 2
