#!/usr/bin/env python3
"""
Optimize character prompts based on feedback.

Uses LLM to generate improvements to the variable part of prompts.
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import config
from src.feedback_analyzer import FeedbackAnalyzer
from src.llm_client import get_llm_client
from src.prompt_manager import get_prompt_manager


def main():
    """Main optimization workflow"""
    llm = get_llm_client()

    print("\n" + "=" * 60)
    print("🔧 Prompt Optimization Tool")
    print("=" * 60)

    # Step 1: Select character
    print("\n[Step 1] Select character to optimize")
    char_id = input("  Enter character ID (A/B): ").strip().upper()

    if char_id not in ["A", "B"]:
        print("❌ Invalid character ID")
        return 1

    # Step 2: Analyze feedback for this character
    print(f"\n[Step 2] Analyzing feedback for character {char_id}...")
    char_issues = FeedbackAnalyzer.analyze_by_character().get(char_id, {})

    if not char_issues:
        print(f"⚠️  No feedback for character {char_id} yet")
        return 0

    print(f"\nTop issues for character {char_id}:")
    for issue_type, count in sorted(char_issues.items(), key=lambda x: x[1], reverse=True)[:5]:
        print(f"  - {issue_type}: {count}")

    # Step 3: Get current prompt
    print(f"\n[Step 3] Loading current prompt...")
    manager = get_prompt_manager(char_id)

    print("\n【Current Variable Part】")
    print("-" * 60)
    print(manager.variable)
    print("-" * 60)

    # Step 4: Generate improvement
    print(f"\n[Step 4] Generating prompt improvement...")

    improvement_prompt = _build_improvement_prompt(char_id, manager.variable, char_issues)

    try:
        suggestion = llm.call(
            system=_get_improvement_system_prompt(),
            user=improvement_prompt,
            temperature=0.7,
            max_tokens=600,
        )
    except Exception as e:
        print(f"❌ LLM generation failed: {e}")
        return 1

    print("\n✨ Suggested Improvements:")
    print("-" * 60)
    print(suggestion)
    print("-" * 60)

    # Step 5: Review and confirm
    print("\n[Step 5] Review suggestions")
    print("Options:")
    print("  'accept' - Use suggestion as-is")
    print("  'merge'  - Merge with current prompt")
    print("  'edit'   - Edit suggestion")
    print("  'skip'   - Skip optimization")

    action = input("  Your choice: ").strip().lower()

    if action == "skip":
        print("⏭️  Skipped")
        return 0

    new_variable = suggestion

    if action == "merge":
        # Simple merge: append suggestion to current
        new_variable = f"{manager.variable}\n\n【补充/改进】\n{suggestion}"

    elif action == "edit":
        print("\nEdit the suggestion (type 'END' on new line to finish):")
        lines = []
        while True:
            line = input()
            if line.strip() == "END":
                break
            lines.append(line)
        new_variable = "\n".join(lines)

    # Step 6: Save
    print(f"\n[Step 6] Saving improved prompt...")

    try:
        manager.update_variable(new_variable)

        from src.logger import get_logger
        logger = get_logger()
        logger.log_prompt_update(
            char_id=char_id,
            section="variable",
            old_content=manager.variable,
            new_content=new_variable,
            reason="Feedback-based optimization",
        )

        print(f"✅ Prompt updated for character {char_id}")
    except Exception as e:
        print(f"❌ Save failed: {e}")
        return 1

    # Step 7: Show new full prompt
    print(f"\n[Step 7] New full system prompt:")
    print("-" * 60)
    print(manager.get_system_prompt())
    print("-" * 60)

    print("\n✅ Optimization complete!")
    print("The updated prompt will be used in the next run.")

    return 0


def _get_improvement_system_prompt() -> str:
    """System prompt for LLM improvement task"""
    return """You are a prompt engineering expert specializing in character AI personalities.
Your task is to improve character prompts based on feedback about their behavior.

Guidelines:
- Keep improvements concise (2-3 paragraphs max)
- Focus on specific, actionable changes
- Preserve the character's core identity
- Address the root causes of reported issues
- Use clear, direct language

Output ONLY the improved variable section, nothing else."""


def _build_improvement_prompt(char_id: str, current_variable: str, issues: dict) -> str:
    """Build the improvement prompt for LLM"""
    char_name = "Elder Sister" if char_id == "A" else "Younger Sister"
    char_domain = "tourism, action, phenomena" if char_id == "A" else "geography, history, architecture"

    issue_summary = "\n".join([
        f"  - {issue}: {count} occurrences"
        for issue, count in sorted(issues.items(), key=lambda x: x[1], reverse=True)[:5]
    ])

    prompt = f"""
Improve the following character prompt based on feedback.

【Character】
Name: {char_name}
ID: {char_id}
Domain: {char_domain}

【Current Variable Section】
{current_variable}

【Feedback Issues】
{issue_summary}

【Task】
Analyze the issues and suggest improvements to the variable section.
Focus on:
1. Addressing the most frequent issues
2. Making tone markers more explicit if there's tone drift
3. Clarifying domain boundaries if there's overstep
4. Improving clarity if there's misunderstanding

Provide the improved variable section:
"""
    return prompt.strip()


if __name__ == "__main__":
    sys.exit(main())
