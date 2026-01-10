import sys
import os
from unittest.mock import MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.director import Director
from src.types import DirectorStatus

def test_multiline_leniency():
    director = Director(enable_fact_check=False)
    
    # Test 3 lines (should PASS with warning)
    response_3lines = "一行目\n二行目\n三行目"
    result = director._check_format(response_3lines)
    assert result["passed"] is True, "Should pass with 3 lines"
    
    # Test 6 lines (should FAIL)
    response_6lines = "1\n2\n3\n4\n5\n6"
    result = director._check_format(response_6lines)
    assert result["passed"] is False, "Should fail with 6 lines"

@patch('src.director.get_llm_client')
def test_state_stability_on_retry(mock_get_llm):
    # Mock LLM client
    mock_llm = MagicMock()
    mock_get_llm.return_value = mock_llm
    
    director = Director(enable_fact_check=False)
    
    # Initial state
    assert director.topic_state.focus_hook == ""
    
    # 1. Trigger a RETRY response (format error: 6 lines)
    bad_response = "1\n2\n3\n4\n5\n6"
    
    # evaluate_response will call _check_format before LLM call
    eval_res = director.evaluate_response(
        frame_description="テストフレーム",
        speaker="A",
        response=bad_response
    )
    
    assert eval_res.status == DirectorStatus.RETRY
    # State should NOT have been updated
    assert director.topic_state.focus_hook == "", "TopicState should not update on RETRY"
    assert director.novelty_guard.turn_count == 0, "NoveltyGuard turn count should not update on RETRY"
    
    # 2. Trigger a PASS response
    # Mock LLM response to return PASS
    mock_llm.call.return_value = '{"status": "PASS", "reason": "Good", "action": "NOOP"}'
    
    good_response = "今日はいい天気だね。"
    eval_res_pass = director.evaluate_response(
        frame_description="晴れた日の景色",
        speaker="A",
        response=good_response,
        turn_number=1
    )
    
    assert eval_res_pass.status == DirectorStatus.PASS
    # State SHOULD have been updated
    assert director.topic_state.focus_hook == "天気", f"TopicState should update on PASS, got {director.topic_state.focus_hook}"
    assert director.novelty_guard.turn_count == 1, "NoveltyGuard turn count should update on PASS"

if __name__ == "__main__":
    try:
        test_multiline_leniency()
        print("✅ test_multiline_leniency passed")
        test_state_stability_on_retry()
        print("✅ test_state_stability_on_retry passed")
    except AssertionError as e:
        print(f"❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ An error occurred: {e}")
        sys.exit(1)
