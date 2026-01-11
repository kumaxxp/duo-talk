import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# Mock dependencies
sys.modules["openai"] = MagicMock()
sys.modules["httpx"] = MagicMock()
sys.modules["duckduckgo_search"] = MagicMock()

from src.director import Director, DirectorStatus

class TestRetryLogicV4(unittest.TestCase):
    def setUp(self):
        self.director = Director(enable_fact_check=False)
        self.director.beat_tracker = MagicMock()
        self.director.beat_tracker.get_current_beat.return_value = "SETUP"
        self.director.llm = MagicMock()

    def test_tone_check_warn(self):
        """Spec 4.1: Score 1 -> WARN"""
        # "綺麗だね" (Yana)
        # Marker: "ね" -> 1
        # Vocab: None
        # Style: 1 sentence, NO exclamation -> 0 (needs exclamation for style hit if <=2 sentences?)
        # Spec 4.4 Yana: "2文以下かつ感嘆符を含む"
        # "綺麗だね" -> No exclamation. Style=0.
        # Score = 1. -> WARN.
        res = self.director._check_tone_markers("A", "綺麗だね")
        # Check that it returns WARN convention (passed=True but with warning, OR explicit WARN status if updated)
        # Since I interpret "Code update": checking the return value.
        # Ideally, helper returns a status or a struct indicating score.
        self.assertEqual(res.get("score"), 1)
        # We will check how this propagates to evaluate_response later

    def test_tone_check_retry(self):
        """Spec 4.1: Score 0 -> RETRY"""
        res = self.director._check_tone_markers("A", "金閣寺は美しい。")
        self.assertEqual(res.get("score"), 0)

    def test_praise_check(self):
        """Spec 5.2: Eval+Affirmation -> RETRY, Eval only -> WARN"""
        # Eval only
        res_warn = self.director._check_praise_words("あゆの答えはすごい。", "B") # "すごい"
        # Only "すごい", no "あなた/君...". "あゆ" is self?
        # Check Affirmation pattern: "あなた/きみ/ユーザー/その答え..." + "正しい..."
        self.assertIn("WARN", res_warn.get("issue", ""))

        # Eval + Affirmation
        res_retry = self.director._check_praise_words("あなたの考えは素晴らしいです。", "B")
        # "あなた" + "素晴らしい" (Eval) + "考え" (Affirmation target?)
        # Wait, pattern is "Evaluative Word" AND "Affirmation to partner".
        # "素晴らしい" is evaluative. "あなたの考え" is target.
        self.assertFalse(res_retry["passed"])

    def test_scatter_check_newline(self):
        """Spec 6.1: Newline is sentence ender"""
        text = "一行目\n二行目\n三行目\n四行目" # 4 sentences
        # Topic check needs keywords. "〜については" etc.
        # To trigger RETRY: 4 sentences AND 3 topics.
        # To trigger WARN: 3 sentences OR 2 topics.
        
        # Test Sentence Count (3 sentences -> WARN)
        text_3 = "一行目\n二行目\n三行目"
        res = self.director._is_scattered_response(text_3)
        # Should be WARN
        self.assertEqual(res.get("level"), "WARN")

    def test_evaluate_response_warn_integration(self):
        """Integration: Tone WARN should result in DirectorStatus.WARN (or PASS with strict instruction)"""
        # If I strictly follow spec: DirectorStatus.WARN exists.
        # So return WARN.
        
        # Make a response that gets Tone Score 1
        with patch.object(self.director, '_check_tone_markers', return_value={"passed": True, "score": 1, "missing": "WARN: Low Score", "found": ["marker"]}), \
             patch.object(self.director, 'llm') as mock_llm:
            
            # Mock LLM to return valid JSON but we focus on hard rule WARN
            mock_llm.call.return_value = '{"status": "PASS", "reason": "ok"}'
            
            res = self.director.evaluate_response("frame", "A", "Low tone score response")
            # If logic implemented correctly, should be WARN (or PASS with INTERVENE)
            # Spec says "DirectorStatus... WARN". So let's aim for WARN status.
            self.assertEqual(res.status, DirectorStatus.WARN)

if __name__ == '__main__':
    unittest.main()
