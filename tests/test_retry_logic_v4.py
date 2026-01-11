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
from src.novelty_guard import LoopBreakStrategy

class TestRetryLogicV4(unittest.TestCase):
    def setUp(self):
        # We'll initialize director inside each test to be safe with mocking
        pass

    def test_tone_check_warn(self):
        """Spec 4.1: Score 1 -> WARN"""
        director = Director(enable_fact_check=False)
        # "そっか" (Yana)
        # markers: None
        # vocab: "そっか" (1 pt)
        # style: None
        res = director._check_tone_markers("A", "そっか")
        self.assertEqual(res.get("status"), DirectorStatus.WARN)
        self.assertEqual(res.get("score"), 1)

    def test_tone_check_pass(self):
        """Spec 4.1: Score 2+ -> PASS"""
        director = Director(enable_fact_check=False)
        # "綺麗だね" (Yana)
        # markers: "だね" (1 pt)
        # vocab: "だね" (1 pt)
        # Total = 2 pt -> PASS
        res = director._check_tone_markers("A", "綺麗だね")
        self.assertEqual(res.get("status"), DirectorStatus.PASS)
        self.assertEqual(res.get("score"), 2)

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
        # New threshold: 3 sentences is PASS unless topics are many
        # "Aです。Bです。\nCです。" -> 3 sentences, 1 topic -> PASS
        res_pass = director._is_scattered_response("これはAです。次はBです。\nさらにCです。")
        self.assertEqual(res_pass.get("status"), DirectorStatus.PASS)

        # 5 sentences -> WARN
        res_warn = director._is_scattered_response("1.Aです。\n2.Bです。\n3.Cです。\n4.Dです。\n5.Eです。")
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
        # "そっか" has vocab_hit=1 but marker_hit=0 and style_hit=0 -> WARN
        eval_res = director.evaluate_response("Description", "A", "そっか")
        
        # Should be WARN status even if LLM said PASS
        if eval_res.status != DirectorStatus.WARN:
            print(f"DEBUG FAILURE: status={eval_res.status}, reason={eval_res.reason}")
        self.assertEqual(eval_res.status, DirectorStatus.WARN)
        self.assertIn("口調", eval_res.reason)

    def test_novelty_guard_katakana_with_middle_dot(self):
        """Test that Katakana with middle dot is extracted as one noun"""
        director = Director(enable_fact_check=False)
        guard = director.novelty_guard
        nouns = guard.extract_nouns("スペース・マウンテンは速い。")
        self.assertIn("スペース・マウンテン", nouns)
        self.assertEqual(len(nouns), 1)

    def test_novelty_guard_deep_loop_strategy(self):
        """Test that 5+ overlaps trigger FORCE_CHANGE_TOPIC"""
        director = Director(enable_fact_check=False)
        guard = director.novelty_guard
        
        # Simulate 5 turns of the same topic
        text = "スペース・マウンテンが凄かった。"
        for _ in range(5):
            guard.check_and_update(text, update=True)
            
        # Check the 6th turn
        res = guard.check_and_update(text, update=False)
        self.assertTrue(res.loop_detected)
        self.assertEqual(res.strategy, LoopBreakStrategy.FORCE_CHANGE_TOPIC)
        self.assertIn("話題強制終了", res.injection)

    def test_director_handles_force_change_topic(self):
        """Test that Director returns RETRY and resets state on deep loop"""
        director = Director(enable_fact_check=False)
        director.last_frame_num = 1 # Avoid reset
        guard = director.novelty_guard
        
        # Manually set a deep loop state
        text = "スペース・マウンテン"
        for _ in range(5):
            guard.check_and_update(text, update=True)
            
        # evaluate_response should trigger Step 0 and return RETRY
        eval_res = director.evaluate_response("Description", "A", text, frame_num=1)
        
        self.assertEqual(eval_res.status, DirectorStatus.RETRY)
        self.assertIn("限界までループ", eval_res.reason)
        # focus_hook should be reset in the result fields
        self.assertEqual(eval_res.focus_hook, "")

    @patch('src.director.get_llm_client')
    def test_novelty_guard_retry_isolation(self, mock_get_llm):
        """Verify that NoveltyGuard state is NOT updated on RETRY, but updated on PASS after commit."""
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm
        director = Director(enable_fact_check=False)
        director.last_frame_num = 1
        
        # 1. First Attempt: Returns RETRY (e.g., Format error)
        # Using a text that contains a specific noun "禁じられた魔法"
        bad_response = "禁じられた魔法について話します。\n" * 10 # Triggers 8+ lines format RETRY
        
        eval_retry = director.evaluate_response("Description", "A", bad_response)
        self.assertEqual(eval_retry.status, DirectorStatus.RETRY)
        
        # NoveltyGuard history should NOT have "禁じられた魔法"
        self.assertFalse(any("魔法" in nouns for nouns in director.novelty_guard.recent_nouns))
        
        # 2. Second Attempt: Returns PASS
        good_response = "わ！ このお守り、すっごい可愛いじゃん！" # Strong character phrase (Score 3+)
        
        mock_llm.call.return_value = json.dumps({
            "scores": {"frame_consistency": 5, "roleplay": 5, "connection": 5, "information_density": 5, "naturalness": 5},
            "status": "PASS",
            "action": "NOOP"
        })
        
        eval_pass = director.evaluate_response("Description", "A", good_response)
        # It's okay if it's WARN or PASS, as long as it's not RETRY for this logic test.
        self.assertIn(eval_pass.status, [DirectorStatus.PASS, DirectorStatus.WARN])
        
        # Still NOT in history before commit
        self.assertFalse(any("お守り" in nouns for nouns in director.novelty_guard.recent_nouns))
        
        # 3. Commit
        director.commit_evaluation(good_response, eval_pass)
        
        # Now "お守り" should be in history, but NOT "魔法"
        self.assertTrue(any("お守り" in nouns for nouns in director.novelty_guard.recent_nouns))
        self.assertFalse(any("魔法" in nouns for nouns in director.novelty_guard.recent_nouns))

if __name__ == '__main__':
    unittest.main()
