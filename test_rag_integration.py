#!/usr/bin/env python3
"""
Quick test to verify RAG system integration with expanded knowledge base
"""

from src.rag import RAGSystem
from src.character import Character

def test_rag_system():
    """Test that RAG system loads and retrieves knowledge correctly"""
    print("=" * 60)
    print("RAG System Integration Test")
    print("=" * 60)

    # Initialize RAG system
    rag_system = RAGSystem()

    # Test Character A (やな) RAG retrieval
    print("\n【Character A (やな) - RAG Retrieval Test】")
    print("-" * 60)

    char_a = Character("A")
    print(f"Character A domains: {char_a.domains}")
    print(f"System prompt length: {len(char_a.system_prompt)} chars")

    # Test query related to sake
    print("\n[Query 1] '酒蔵を見学する場合のポイント'")
    hints_a = char_a._get_rag_hints(
        query="酒蔵を見学する場合のポイント",
        top_k=2
    )
    for i, hint in enumerate(hints_a, 1):
        print(f"  Hint {i}: {hint[:100]}...")

    # Test query related to cultural philosophy
    print("\n[Query 2] '情報を食べるという哲学について'")
    hints_a = char_a._get_rag_hints(
        query="情報を食べるという哲学について",
        top_k=2
    )
    for i, hint in enumerate(hints_a, 1):
        print(f"  Hint {i}: {hint[:100]}...")

    # Test query related to human action
    print("\n[Query 3] '観光客の行動パターン'")
    hints_a = char_a._get_rag_hints(
        query="観光客の行動パターン",
        top_k=2
    )
    for i, hint in enumerate(hints_a, 1):
        print(f"  Hint {i}: {hint[:100]}...")

    # Test Character B (あゆ) RAG retrieval
    print("\n\n【Character B (あゆ) - RAG Retrieval Test】")
    print("-" * 60)

    char_b = Character("B")
    print(f"Character B domains: {char_b.domains}")
    print(f"System prompt length: {len(char_b.system_prompt)} chars")

    # Test query related to etiquette
    print("\n[Query 1] '神社の参拝作法'")
    hints_b = char_b._get_rag_hints(
        query="神社の参拝作法",
        top_k=2
    )
    for i, hint in enumerate(hints_b, 1):
        print(f"  Hint {i}: {hint[:100]}...")

    # Test query related to natural science
    print("\n[Query 2] '虹の原理と光の屈折'")
    hints_b = char_b._get_rag_hints(
        query="虹の原理と光の屈折",
        top_k=2
    )
    for i, hint in enumerate(hints_b, 1):
        print(f"  Hint {i}: {hint[:100]}...")

    # Test query related to gadgets (should retrieve if not filtered)
    print("\n[Query 3] 'AI基地建設のためのGPU情報'")
    hints_b = char_b._get_rag_hints(
        query="AI基地建設のためのGPU情報",
        top_k=2
    )
    for i, hint in enumerate(hints_b, 1):
        print(f"  Hint {i}: {hint[:100]}...")

    print("\n" + "=" * 60)
    print("✅ RAG System Integration Test Complete")
    print("=" * 60)

if __name__ == "__main__":
    test_rag_system()
