#!/usr/bin/env python3
"""
Interactive tool for suggesting and adding knowledge to character knowledge bases.

Workflow:
1. Analyze recent feedback
2. Suggest improvements based on issues
3. LLM generates knowledge candidates
4. User confirms and edits
5. Add to knowledge base
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import config
from src.feedback_analyzer import FeedbackAnalyzer
from src.llm_client import get_llm_client
from src.knowledge_manager import get_knowledge_manager


def main():
    """Main interactive workflow"""
    llm = get_llm_client()

    print("\n" + "=" * 60)
    print("📚 Knowledge Base Improvement Assistant")
    print("=" * 60)

    # Step 1: Analyze feedback
    print("\n[Step 1] Analyzing recent feedback...")
    trends = FeedbackAnalyzer.analyze_trends()

    if not trends:
        print("⚠️  No feedback recorded yet.")
        print("Please run some tests and provide feedback first.")
        return 1

    print("\nRecent feedback trends:")
    for issue_type, count in list(trends.items())[:5]:
        print(f"  - {issue_type}: {count} issues")

    # Step 2: Select character
    print("\n[Step 2] Select target character")
    char_id = input("  Enter character ID (A/B): ").strip().upper()

    if char_id not in ["A", "B"]:
        print("❌ Invalid character ID")
        return 1

    char_issues = FeedbackAnalyzer.analyze_by_character().get(char_id, {})
    if char_issues:
        print(f"\nCharacter {char_id} top issues:")
        for issue_type, count in sorted(char_issues.items(), key=lambda x: x[1], reverse=True)[:3]:
            print(f"  - {issue_type}: {count}")

    # Step 3: Select knowledge type
    print("\n[Step 3] Select knowledge type to add")
    print("  1. General knowledge (facts, information)")
    print("  2. Persona knowledge (character traits)")
    print("  3. Lore knowledge (world building)")
    print("  4. Example knowledge (good response examples)")

    knowledge_type = input("  Enter choice (1-4): ").strip()
    type_map = {
        "1": "general",
        "2": "persona",
        "3": "lore",
        "4": "example",
    }
    doc_type = type_map.get(knowledge_type, "general")

    # Step 4: Enter topic
    print("\n[Step 4] Enter topic name")
    topic = input("  Topic (e.g., 'architecture', 'tone_markers'): ").strip()

    if not topic:
        print("❌ Topic cannot be empty")
        return 1

    # Step 5: LLM generates candidates
    print(f"\n[Step 5] Generating knowledge candidates...")

    prompt = _build_generation_prompt(char_id, topic, doc_type, char_issues)

    try:
        candidates = llm.call(
            system="You are a knowledge base expert for AI characters. Create clear, structured knowledge entries.",
            user=prompt,
            temperature=0.7,
            max_tokens=800,
        )
    except Exception as e:
        print(f"❌ LLM generation failed: {e}")
        return 1

    print("\n✨ Generated Knowledge Candidates:")
    print("-" * 60)
    print(candidates)
    print("-" * 60)

    # Step 6: User confirms/edits
    print("\n[Step 6] Review and confirm")
    print("Options:")
    print("  'yes'   - Use generated content as-is")
    print("  'edit'  - Edit before saving")
    print("  'skip'  - Skip this knowledge")

    action = input("  Your choice: ").strip().lower()

    if action == "skip":
        print("⏭️  Skipped")
        return 0

    content = candidates

    if action == "edit":
        print("\nEnter new content (type 'END' on a new line to finish):")
        lines = []
        while True:
            line = input()
            if line.strip() == "END":
                break
            lines.append(line)
        content = "\n".join(lines)

    if not content.strip():
        print("❌ Content cannot be empty")
        return 1

    # Step 7: Save to knowledge base
    print("\n[Step 7] Saving to knowledge base...")
    manager = get_knowledge_manager(char_id)

    try:
        filepath = manager.add_knowledge(
            topic=topic,
            content=content,
            doc_type=doc_type,
            source="suggest_knowledge.py",
        )
        print(f"✅ Saved to {filepath}")
    except Exception as e:
        print(f"❌ Save failed: {e}")
        return 1

    # Step 8: Show summary
    print("\n[Step 8] Knowledge base summary")
    print(manager.export_summary())

    print("\n✅ Knowledge addition complete!")
    print(f"   {len(manager.list_topics())} total topics in char {char_id}'s knowledge base")

    return 0


def _build_generation_prompt(char_id: str, topic: str, doc_type: str, issues: dict) -> str:
    """Build the prompt for LLM generation"""
    char_name = "Elder Sister" if char_id == "A" else "Younger Sister"

    prompt = f"""
Generate a knowledge entry for character {char_id} ({char_name}).

【Character Details】
- ID: {char_id}
- Type: {doc_type}
- Topic: {topic}

【Recent Issues】
{_format_issues(issues)}

【Requirements】
- Clear and structured format
- Markdown-friendly
- 1-2 paragraphs
- Actionable and specific
- Aligned with character's expertise area

【Format】
```
# {topic}

[Clear explanation/description]
```

Generate the knowledge entry:
"""
    return prompt.strip()


def _format_issues(issues: dict) -> str:
    """Format issues for prompt"""
    if not issues:
        return "  - No specific issues recorded"

    lines = []
    for issue_type, count in sorted(issues.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"  - {issue_type}: {count}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
