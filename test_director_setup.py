#!/usr/bin/env python3
"""
Quick test to verify Director system prompt is loaded correctly
"""

from src.director import Director
from src.prompt_manager import get_prompt_manager

def test_director_setup():
    """Test that Director loads system prompt correctly"""
    print("=" * 60)
    print("Director Setup Test")
    print("=" * 60)

    # Test PromptManager for director
    print("\n【PromptManager Test】")
    pm = get_prompt_manager("director")
    print(f"Base path: {pm.base_path}")
    print(f"Fixed prompt loaded: {len(pm.fixed) > 0} ({len(pm.fixed)} chars)")
    print(f"Variable prompt loaded: {len(pm.variable) > 0} ({len(pm.variable)} chars)")

    if pm.fixed:
        print(f"\n【Fixed Prompt Preview】")
        print(pm.fixed[:200] + "...")

    if pm.variable:
        print(f"\n【Variable Prompt Preview】")
        print(pm.variable[:200] + "...")

    # Test Director initialization
    print("\n【Director Initialization Test】")
    director = Director()
    print(f"Director system prompt loaded: {len(director.system_prompt) > 0}")
    print(f"System prompt length: {len(director.system_prompt)} chars")

    if director.system_prompt:
        print(f"\n【Director System Prompt Preview】")
        print(director.system_prompt[:300] + "...")

    print("\n" + "=" * 60)
    print("✅ Director Setup Test Complete")
    print("=" * 60)

if __name__ == "__main__":
    test_director_setup()
