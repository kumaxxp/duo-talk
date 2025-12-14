"""
Knowledge management: add, update, and manage character knowledge bases.
"""

import json
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

from src.config import config
from src.logger import get_logger


class KnowledgeManager:
    """Manages character knowledge bases"""

    def __init__(self, char_id: str):
        """
        Initialize KnowledgeManager for a character.

        Args:
            char_id: "A" or "B"
        """
        self.char_id = char_id.lower()
        self.domain_path = config.rag_data_dir / f"char_{self.char_id}_domain"
        self.domain_path.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.domain_path / "_metadata.json"
        self._load_metadata()

    def _load_metadata(self) -> None:
        """Load metadata about knowledge base"""
        if self.metadata_file.exists():
            self.metadata = json.loads(self.metadata_file.read_text(encoding="utf-8"))
        else:
            self.metadata = {
                "char_id": self.char_id,
                "created": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "documents": {},
            }

    def _save_metadata(self) -> None:
        """Save metadata"""
        self.metadata["last_updated"] = datetime.now().isoformat()
        self.metadata_file.write_text(json.dumps(self.metadata, ensure_ascii=False, indent=2))

    def add_knowledge(
        self,
        topic: str,
        content: str,
        doc_type: str = "general",
        source: str = None,
    ) -> str:
        """
        Add or update knowledge in the character's domain.

        Args:
            topic: Topic name (becomes filename)
            content: Knowledge content (Markdown format recommended)
            doc_type: "general" | "persona" | "lore" | "example"
            source: Optional source attribution

        Returns:
            Path to saved file
        """
        filename = f"{topic}.md"
        filepath = self.domain_path / filename

        filepath.write_text(content, encoding="utf-8")

        # Update metadata
        self.metadata["documents"][topic] = {
            "type": doc_type,
            "size": len(content),
            "source": source or "manual_entry",
            "added": datetime.now().isoformat(),
        }

        self._save_metadata()

        # Log the update
        logger = get_logger()
        logger.log_prompt_update(
            char_id=self.char_id,
            section="knowledge",
            old_content="",
            new_content=content,
            reason=f"Added {doc_type} knowledge: {topic}",
        )

        return str(filepath)

    def update_knowledge(self, topic: str, content: str) -> str:
        """
        Update existing knowledge.

        Args:
            topic: Topic name
            content: New content

        Returns:
            Path to file
        """
        filepath = self.domain_path / f"{topic}.md"
        old_content = filepath.read_text() if filepath.exists() else ""

        filepath.write_text(content, encoding="utf-8")

        # Update metadata
        if topic not in self.metadata["documents"]:
            self.metadata["documents"][topic] = {}

        self.metadata["documents"][topic]["updated"] = datetime.now().isoformat()
        self._save_metadata()

        # Log
        logger = get_logger()
        logger.log_prompt_update(
            char_id=self.char_id,
            section="knowledge",
            old_content=old_content,
            new_content=content,
            reason=f"Updated knowledge: {topic}",
        )

        return str(filepath)

    def get_knowledge(self, topic: str) -> Optional[str]:
        """
        Get knowledge content by topic.

        Args:
            topic: Topic name

        Returns:
            Content or None if not found
        """
        filepath = self.domain_path / f"{topic}.md"
        if filepath.exists():
            return filepath.read_text(encoding="utf-8")
        return None

    def list_topics(self) -> List[str]:
        """
        List all topics in this character's knowledge base.

        Returns:
            List of topic names
        """
        return [f.stem for f in self.domain_path.glob("*.md") if f.name != "_metadata.json"]

    def list_by_type(self, doc_type: str) -> List[str]:
        """
        List topics by type.

        Args:
            doc_type: Document type filter

        Returns:
            List of matching topics
        """
        matching = []
        for topic, meta in self.metadata.get("documents", {}).items():
            if meta.get("type") == doc_type:
                matching.append(topic)
        return matching

    def delete_knowledge(self, topic: str) -> bool:
        """
        Delete knowledge by topic.

        Args:
            topic: Topic to delete

        Returns:
            True if successful
        """
        filepath = self.domain_path / f"{topic}.md"
        if filepath.exists():
            filepath.unlink()
            if topic in self.metadata["documents"]:
                del self.metadata["documents"][topic]
            self._save_metadata()
            return True
        return False

    def export_summary(self) -> str:
        """
        Export a summary of this character's knowledge base.

        Returns:
            Formatted summary
        """
        lines = [
            f"Knowledge Base Summary for Character {self.char_id.upper()}",
            "=" * 50,
            "",
        ]

        topics = self.list_topics()
        if not topics:
            lines.append("No knowledge documents yet.")
        else:
            lines.append(f"Total documents: {len(topics)}\n")

            # Group by type
            doc_types = set()
            for meta in self.metadata.get("documents", {}).values():
                doc_types.add(meta.get("type", "general"))

            for doc_type in sorted(doc_types):
                type_topics = self.list_by_type(doc_type)
                if type_topics:
                    lines.append(f"【{doc_type.upper()}】")
                    for topic in type_topics:
                        meta = self.metadata["documents"][topic]
                        size = meta.get("size", 0)
                        lines.append(f"  - {topic} ({size} bytes)")
                    lines.append("")

        return "\n".join(lines)


class KnowledgeRepository:
    """Manages knowledge for both characters"""

    def __init__(self):
        self.managers = {}

    def get_manager(self, char_id: str) -> KnowledgeManager:
        """Get or create KnowledgeManager for a character"""
        if char_id not in self.managers:
            self.managers[char_id] = KnowledgeManager(char_id)
        return self.managers[char_id]

    def add_shared_knowledge(self, topic: str, content: str) -> Dict[str, str]:
        """
        Add knowledge that both characters can access.

        Args:
            topic: Topic name
            content: Knowledge content

        Returns:
            Dict of filepaths for each character
        """
        results = {}
        for char_id in ["A", "B"]:
            manager = self.get_manager(char_id)
            path = manager.add_knowledge(topic, content, doc_type="shared")
            results[char_id] = path
        return results


# Global repository instance
_repository: Optional[KnowledgeRepository] = None


def get_knowledge_manager(char_id: str) -> KnowledgeManager:
    """Get KnowledgeManager for a character"""
    global _repository
    if _repository is None:
        _repository = KnowledgeRepository()
    return _repository.get_manager(char_id)


def get_knowledge_repository() -> KnowledgeRepository:
    """Get global knowledge repository"""
    global _repository
    if _repository is None:
        _repository = KnowledgeRepository()
    return _repository
