import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import json

# Mock dependencies to avoid import errors in this environment
sys.modules['openai'] = MagicMock()
sys.modules['httpx'] = MagicMock()
sys.modules['duckduckgo_search'] = MagicMock()

# Import after mocking
from src.director import Director
from src.types import DirectorStatus

class TestRetryLogicV4(unittest.TestCase):
    def setUp(self):
        # We'll initialize director inside each test to be safe with mocking
        pass

    def test_tone_check_warn(self):
        """Spec 4.1: Score 1 -> WARN"""
        director = Director(enable_fact_check=False)
        # "綺麗だね" (Yana)
        # Tone markers: ["わ！", "へ？", "よね", "かな", "かも"] -> None in "綺麗だね"
        # Vocab: ["やだ", "ほんと", "えー", "うーん", "すっごい", "そっか", "だね", "ね。"] -> "だね" fits. (Score 1)
        res = director._check_tone_markers("A", "綺麗だね")
        self.assertEqual(res.get("status"), DirectorStatus.WARN)
        self.assertEqual(res.get("score"), 1)

    def test_tone_check_retry(self):
        """Spec 4.1: Score 0 -> RETRY"""
        director = Director(enable_fact_check=False)
        # "金閣寺は美しい。" (Yana - no markers, no styles)
        res = director._check_tone_markers("A", "金閣寺は美しい。")
        self.assertEqual(res.get("status"), DirectorStatus.RETRY)
        self.assertEqual(res.get("score"), 0)

    def test_praise_check(self):
        """Spec 5.2: Eval+Affirmation -> RETRY, Eval only -> WARN"""
        director = Director(enable_fact_check=False)
        # Eval only
        res_warn = director._check_praise_words("あゆの答えはすごい。", "B")
        self.assertEqual(res_warn.get("status"), DirectorStatus.WARN)
    
        # Eval + Affirmation
        res_retry = director._check_praise_words("あなたの考えは素晴らしいです。", "B")
        self.assertEqual(res_retry.get("status"), DirectorStatus.RETRY)

    def test_scatter_check_newline(self):
        """Spec 7.1: Newline sentence counting and thresholds"""
        director = Director(enable_fact_check=False)
        # 3 sentences or 2 topics -> WARN
        # "Aです。Bです。\nCです。" -> 3 sentences
        res_warn = director._is_scattered_response("これはAです。次はBです。\nさらにCです。")
        self.assertEqual(res_warn.get("status"), DirectorStatus.WARN)
        
        # 4 sentences AND 3 topics -> RETRY
        # "金閣寺についてです。銀閣寺についても話しましょう。\n清水寺の話もしたいです。京都は広いですね。"
        # Sentences: 4
        # Topics:
        # 1. 金閣寺についてです (r"について(も)?(です|...)")
        # 2. 銀閣寺についても話しましょう (r"について(も)?(です|...)") -> "話" matches
        # 3. 清水寺の話もしたいです (r"の話(を|で|に|も)") -> "も" matches
        long_response = "金閣寺についてです。銀閣寺についても話しましょう。\n清水寺の話もしたいです。京都は広いですね。"
        res_retry = director._is_scattered_response(long_response)
        self.assertEqual(res_retry.get("status"), DirectorStatus.RETRY)

    @patch('src.director.get_llm_client')
    def test_evaluate_response_warn_integration(self, mock_get_llm):
        """Test that WARN status promotes PASS to WARN in evaluate_response"""
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm
        
        director = Director(enable_fact_check=False)
        
        # Mock LLM to return a PASS score (e.g., 5.0)
        mock_llm.call.return_value = json.dumps({
            "scores": {
                "frame_consistency": 5,
                "roleplay": 5,
                "connection": 5,
                "information_density": 5,
                "naturalness": 5
            },
            "status": "PASS",
            "action": "NOOP",
            "reason": "Perfect"
        })
        
        # Trigger a static warning (e.g. slight tone issue)
        # "綺麗だね" has Score 1 -> WARN
        eval_res = director.evaluate_response("Description", "A", "綺麗だね")
        
        # Should be WARN status even if LLM said PASS
        if eval_res.status != DirectorStatus.WARN:
            print(f"DEBUG FAILURE: status={eval_res.status}, reason={eval_res.reason}")
        self.assertEqual(eval_res.status, DirectorStatus.WARN)
        self.assertIn("口調", eval_res.reason)

if __name__ == '__main__':
    unittest.main()
