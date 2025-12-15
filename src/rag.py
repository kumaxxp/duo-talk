"""
RAG (Retrieval-Augmented Generation) system for character-specific knowledge.
"""

from pathlib import Path
from typing import List, Tuple, Optional
from rapidfuzz import fuzz

from src.config import config


class RAGDatabase:
    """Character-specific knowledge retrieval system"""

    def __init__(self, char_id: str):
        """
        Initialize RAG database for a character.

        Args:
            char_id: "A" or "B"
        """
        self.char_id = char_id
        # Convert to lowercase for directory path
        char_id_lower = char_id.lower()
        self.domain_path = config.rag_data_dir / f"char_{char_id_lower}_domain"
        self.knowledge: List[Tuple[str, str, str]] = []  # (domain, path, content)
        self._load_knowledge()

    def _load_knowledge(self) -> None:
        """Load all knowledge files from character domain directory"""
        if not self.domain_path.exists():
            print(f"Warning: Knowledge domain path not found: {self.domain_path}")
            return

        self.knowledge = []
        for md_file in self.domain_path.glob("**/*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                domain = md_file.stem
                self.knowledge.append((domain, str(md_file.relative_to(self.domain_path)), content))
            except Exception as e:
                print(f"Error loading {md_file}: {e}")

    def retrieve(
        self,
        query: Optional[str],
        top_k: int = 3,
        threshold: float = 0.4,
    ) -> List[Tuple[str, str]]:
        """
        Retrieve relevant knowledge snippets for a query.

        Args:
            query: Search query (frame description or previous speech)
            top_k: Number of results to return
            threshold: Minimum similarity threshold

        Returns:
            List of (domain, snippet) tuples
        """
        if not self.knowledge:
            return []

        # Guard against None or empty query
        if not query:
            return []

        scored_results = []
        for domain, path, content in self.knowledge:
            # Simple BM25-like scoring using token overlap + string similarity
            score = self._score_similarity(query, content)
            if score >= threshold:
                snippet = self._extract_snippet(content)
                scored_results.append((score, domain, snippet))

        # Sort by score and return top_k
        scored_results.sort(key=lambda x: x[0], reverse=True)
        return [(domain, snippet) for _, domain, snippet in scored_results[:top_k]]

    def _score_similarity(self, query: str, content: str) -> float:
        """Score similarity between query and content (Japanese-aware)"""
        # Check exact match
        if query in content:
            return 1.0

        # Check if any part of query appears in content
        query_lower = query.lower()
        content_lower = content.lower()

        if query_lower in content_lower:
            return 1.0

        # For Japanese text: character n-gram matching
        # Extract 2-character sequences from query
        query_chars = set()
        for i in range(len(query) - 1):
            query_chars.add(query[i:i+2])

        if not query_chars:
            return 0.0

        # Count how many query n-grams appear in content
        content_chars = set()
        for i in range(len(content) - 1):
            content_chars.add(content[i:i+2])

        if not content_chars:
            return 0.0

        intersection = len(query_chars & content_chars)
        return intersection / len(query_chars)

    def _extract_snippet(self, content: str, max_length: int = 200) -> str:
        """Extract a meaningful snippet from content"""
        lines = content.strip().split("\n")
        # Skip front matter / metadata
        start_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("---"):
                start_idx = i + 1
            elif line.strip() and not line.startswith("#"):
                start_idx = i
                break

        # Build snippet
        snippet = ""
        for line in lines[start_idx:]:
            if len(snippet) + len(line) > max_length:
                break
            snippet += line + "\n"

        return snippet.strip() or lines[0][:max_length]


class RAGSystem:
    """Manager for both characters' RAG databases"""

    def __init__(self):
        self.char_a_rag = RAGDatabase("A")
        self.char_b_rag = RAGDatabase("B")

    def retrieve_for_character(
        self,
        char_id: str,
        query: str,
        top_k: int = 3,
    ) -> List[Tuple[str, str]]:
        """
        Retrieve knowledge for a specific character.

        Args:
            char_id: "A" or "B"
            query: Search query
            top_k: Number of results

        Returns:
            List of (domain, snippet) tuples
        """
        rag = self.char_a_rag if char_id == "A" else self.char_b_rag
        return rag.retrieve(query, top_k=top_k)


# Global RAG system instance
_rag_system: Optional[RAGSystem] = None


def get_rag_system() -> RAGSystem:
    """Get or create global RAG system"""
    global _rag_system
    if _rag_system is None:
        _rag_system = RAGSystem()
    return _rag_system
