import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.director import Director
from src.types import TopicState

def test_quote_leniency():
    director = Director()
    
    # Test starting with 「
    response1 = "「わ！金閣寺だね！」"
    result1 = director._check_format(response1)
    assert result1["passed"] is True, "Should pass even if starting with 「"
    
    # Test multiple 「」
    response2 = "「こんにちは」と言ってから「さようなら」と言いました。"
    result2 = director._check_format(response2)
    assert result2["passed"] is True, "Should pass even with multiple 「」"

def test_topic_transition():
    state = TopicState()
    state.switch_topic("金閣寺")
    
    # After 0 turns, should not be able to switch (wait for at least one response)
    # Actually TopicState.advance_depth is called during the turn processing.
    
    # Simulate first turn
    state.advance_depth()
    assert state.turns_on_hook == 1
    assert state.can_switch_topic() is True, "Should be able to switch after 1 turn"

if __name__ == "__main__":
    try:
        test_quote_leniency()
        print("✅ test_quote_leniency passed")
        test_topic_transition()
        print("✅ test_topic_transition passed")
    except AssertionError as e:
        print(f"❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ An error occurred: {e}")
        sys.exit(1)
