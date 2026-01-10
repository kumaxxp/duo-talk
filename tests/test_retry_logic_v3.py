
import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.director import Director, DirectorStatus

class TestRetryLogicV3(unittest.TestCase):
    def setUp(self):
        self.director = Director(enable_fact_check=False)
        # Mock dependencies
        self.director.beat_tracker = MagicMock()
        self.director.beat_tracker.get_current_beat.return_value = "SETUP"
        self.director.beat_tracker.get_beat_info.return_value = {}
        self.director.llm = MagicMock()

    def test_normalize_text(self):
        # 引用・台本除外
        self.assertEqual(self.director._normalize_text("「すごいね」"), "すごいね") # Unwrapped
        self.assertEqual(self.director._normalize_text("ユーザーが「すごい」と言った"), "ユーザーがと言った") # Quotes removed
        self.assertEqual(self.director._normalize_text("（笑）それは無理"), "それは無理") # Parentheses removed

        # 記号正規化
        self.assertEqual(self.director._normalize_text("すごい！！"), "すごい！")
        self.assertEqual(self.director._normalize_text("うん。。"), "うん。")
        
        # 空白正規化
        self.assertEqual(self.director._normalize_text("  あ  い  "), "あ い")

    def test_tone_check_yana(self):
        # Marker hit (ね)
        res = self.director._check_tone_markers("A", "そうですね") # "ね" included
        self.assertGreaterEqual(res["score"], 1, "Should have score for 'ね'")

        # Vocab hit (すっごい)
        res = self.director._check_tone_markers("A", "すっごい綺麗") 
        self.assertGreaterEqual(res["score"], 1, "Should have score for 'すっごい'")
        
        # Style hit (Short + Exclamation)
        res = self.director._check_tone_markers("A", "まじで！？")
        # marker "ね" not strictly there, vocab "まじ" not in list. 
        # But style: 2 sentences (count ! ?) <= 2 and has exclamation.
        # "まじで！？" -> chars: まじで！(1)？(1) -> 2 sentences? 
        # Implementaion: count("。")+count("！")+count("？"). 
        # "まじで！？" -> ！ + ？ = 2 counts. <= 2. OK.
        self.assertGreaterEqual(res.get("score", 0), 1, "Should hit style score")

        # Score 2 (Pass)
        res = self.director._check_tone_markers("A", "すっごいね！") # 'すっごい'(vocab) + 'ね'(marker) + style?
        self.assertGreaterEqual(res["score"], 2)
        self.assertTrue(res["passed"])

        # Score 0 (Fail)
        res = self.director._check_tone_markers("A", "金閣寺は美しい。")
        self.assertEqual(res["score"], 0)
        self.assertFalse(res["passed"])

    def test_tone_check_ayu(self):
        # Marker hit (です)
        res = self.director._check_tone_markers("B", "そうです。")
        self.assertGreaterEqual(res["score"], 1)

        # Style hit (Polite x 2)
        # "そうです。行きました。" -> です(1) + ました(1) = 2.
        res = self.director._check_tone_markers("B", "そうです。行きました。") 
        # "です" matches marker (1 point).
        # polite_count = 2 (1 point for style).
        # Total 2.
        self.assertGreaterEqual(res["score"], 2)
        
        # Score 1 (Warn)
        res = self.director._check_tone_markers("B", "目安。") # "目安" is in vocab. No marker.
        self.assertEqual(res["score"], 1)
        # Passed is True for WARN
        self.assertTrue(res["passed"]) 

    def test_scoring_system_retry(self):
        # Mock LLM to return low score
        low_score_json = """
        {
            "scores": {
                "frame_consistency": 3,
                "roleplay": 3,
                "connection": 3,
                "information_density": 3,
                "naturalness": 4
            },
            "status": "PASS",
            "reason": "Test Low Score",
            "action": "NOOP"
        }
        """
        # Avg = 16/5 = 3.2 (< 3.5 -> RETRY)
        self.director.llm.call.return_value = low_score_json
        
        # Mock helper methods to pass hard rules
        with patch.object(self.director, '_check_format', return_value={"passed": True}):
             with patch.object(self.director, '_check_tone_markers', return_value={"passed": True, "score": 2, "found": [], "missing": ""}):
                  eval_res = self.director.evaluate_response("frame", "A", "Test Response")
                  self.assertEqual(eval_res.status, DirectorStatus.RETRY)
                  self.assertIn("Test Low Score", eval_res.reason)

    def test_scoring_system_warn(self):
        # Mock LLM to return warn score (3.5 <= avg < 4.0)
        warn_score_json = """
        {
            "scores": {
                "frame_consistency": 4,
                "roleplay": 4,
                "connection": 3,
                "information_density": 3,
                "naturalness": 4
            },
            "status": "PASS",
            "reason": "Test Warn Score",
            "action": "NOOP"
        }
        """
        # Avg = 18/5 = 3.6 (WARN range)
        self.director.llm.call.return_value = warn_score_json
        
        with patch.object(self.director, '_check_format', return_value={"passed": True}):
             with patch.object(self.director, '_check_tone_markers', return_value={"passed": True, "score": 2, "found": [], "missing": ""}):
                  # We need to capture the print output or use MagicMock for dependency injection of next_instruction
                  # But since create_task returns DirectorEvaluation which has next_instruction is None for NOOP,
                  # BUT I updated logic to upgrade to INTERVENE if warnings exist.
                  
                  # Wait, logic was:
                  # if warning_messages: action = "INTERVENE"
                  
                  eval_res = self.director.evaluate_response("frame", "A", "Test Response")
                  
                  # Should be PASS status
                  self.assertEqual(eval_res.status, DirectorStatus.PASS)
                  # Should have upgraded to INTERVENE because of Score Warning
                  if eval_res.action != "INTERVENE":
                       print(f"DEBUG: eval_res content: {eval_res}")
                  self.assertEqual(eval_res.action, "INTERVENE")
                  # Instruction should contain Score warning
                  self.assertIn("[Score: 3.6 (Low)]", eval_res.next_instruction)

if __name__ == '__main__':
    unittest.main()
