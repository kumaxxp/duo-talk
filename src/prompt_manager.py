"""
Prompt management: separation of fixed/variable/templates
"""

from pathlib import Path
from typing import Dict, Optional
import json

from src.config import config


class PromptManager:
    """
    Manages character and director prompts with fixed/variable/template separation.

    This allows systematic improvement of prompts by only modifying the
    variable parts while keeping safety-critical fixed parts unchanged.
    """

    def __init__(self, char_id: str, jetracer_mode: bool = False):
        """
        Initialize PromptManager for a character or director.

        Args:
            char_id: "A", "B", or "director"
            jetracer_mode: True for JetRacer mode, False for general conversation
        """
        self.char_id = char_id.lower() if char_id in ["A", "B"] else char_id
        self.jetracer_mode = jetracer_mode

        # Special handling for director vs character paths
        if self.char_id == "director":
            self.base_path = config.project_root / "persona" / "director"
        else:
            self.base_path = config.project_root / "persona" / f"char_{self.char_id}"

        # Load prompt parts (mode-dependent)
        self.fixed = self._load_system_prompt()
        self.variable = self._load_file("system_variable.txt")
        self.templates = self._load_templates("templates.txt")

        # Convenience property
        self.system_prompt = self.get_system_prompt()

    def _load_system_prompt(self) -> str:
        """
        Load system prompt based on mode.
        
        - jetracer_mode=True: system_jetracer.txt
        - jetracer_mode=False: system_general.txt
        - Fallback: system_fixed.txt (for backward compatibility)
        """
        if self.jetracer_mode:
            filename = "system_jetracer.txt"
        else:
            filename = "system_general.txt"
        
        path = self.base_path / filename
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        
        # Fallback to system_fixed.txt for backward compatibility
        fallback_path = self.base_path / "system_fixed.txt"
        if fallback_path.exists():
            return fallback_path.read_text(encoding="utf-8").strip()
        
        return ""

    def _load_file(self, filename: str) -> str:
        """Load a prompt file, return empty string if not found"""
        path = self.base_path / filename
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        return ""

    def _load_templates(self, filename: str) -> Dict[str, str]:
        """Load templates from file and parse into dict"""
        path = self.base_path / filename
        if not path.exists():
            return {}

        content = path.read_text(encoding="utf-8")
        templates = {}
        current_template = None
        current_content = []

        for line in content.split("\n"):
            # Detect template header (e.g., "# TEMPLATE_NAME:")
            if line.startswith("# "):
                if current_template:
                    templates[current_template] = "\n".join(current_content).strip()
                current_template = line[2:].rstrip(":")
                current_content = []
            elif current_template and line.strip():
                current_content.append(line)

        # Save last template
        if current_template:
            templates[current_template] = "\n".join(current_content).strip()

        return templates

    def get_system_prompt(self) -> str:
        """
        Get the complete system prompt (fixed + variable).

        Returns:
            Combined prompt text
        """
        parts = []
        if self.fixed:
            parts.append(self.fixed)
        if self.variable:
            parts.append(f"\n【可変部分（改善対象）】\n{self.variable}")

        return "\n".join(parts)

    def update_variable(self, new_variable: str) -> None:
        """
        Update only the variable part of the prompt.

        Args:
            new_variable: New variable prompt text
        """
        path = self.base_path / "system_variable.txt"
        path.write_text(new_variable, encoding="utf-8")
        self.variable = new_variable

    def get_template(self, template_name: str) -> Optional[str]:
        """
        Get a template by name.

        Args:
            template_name: Name of the template (e.g., "UNKNOWN", "SURPRISE")

        Returns:
            Template text or None if not found
        """
        return self.templates.get(template_name)

    def list_templates(self) -> list:
        """List all available template names"""
        return list(self.templates.keys())

    def export_metadata(self) -> dict:
        """
        Export metadata about this prompt.

        Returns:
            Dict with information about prompt structure
        """
        return {
            "char_id": self.char_id,
            "jetracer_mode": self.jetracer_mode,
            "fixed_lines": len(self.fixed.split("\n")) if self.fixed else 0,
            "variable_lines": len(self.variable.split("\n")) if self.variable else 0,
            "template_count": len(self.templates),
            "template_names": list(self.templates.keys()),
        }


class PromptRepository:
    """Manages multiple prompts with versioning support"""

    def __init__(self):
        self.prompts = {}
        self._history_file = config.log_dir / "prompt_history.jsonl"

    def get_manager(self, char_id: str, jetracer_mode: bool = False) -> PromptManager:
        """
        Get or create PromptManager for a character.
        
        Args:
            char_id: Character ID ("A", "B", or "director")
            jetracer_mode: True for JetRacer mode, False for general conversation
        """
        # キーにモードを含めてキャッシュを分離
        cache_key = f"{char_id}_{jetracer_mode}"
        if cache_key not in self.prompts:
            self.prompts[cache_key] = PromptManager(char_id, jetracer_mode=jetracer_mode)
        return self.prompts[cache_key]

    def save_version(self, char_id: str, version_name: str) -> None:
        """
        Save current prompt as a named version.

        Args:
            char_id: Character ID
            version_name: Name for this version (e.g., "v1.0", "tone_improved")
        """
        manager = self.get_manager(char_id)
        version_data = {
            "char_id": char_id,
            "version": version_name,
            "timestamp": __import__("datetime").datetime.now().isoformat(),
            "fixed": manager.fixed,
            "variable": manager.variable,
            "metadata": manager.export_metadata(),
        }

        with open(self._history_file, "a", encoding="utf-8") as f:
            f.write(__import__("json").dumps(version_data, ensure_ascii=False) + "\n")

    def list_versions(self, char_id: str) -> list:
        """List all saved versions of a character's prompt"""
        versions = []
        if not self._history_file.exists():
            return versions

        with open(self._history_file, encoding="utf-8") as f:
            for line in f:
                data = __import__("json").loads(line)
                if data.get("char_id") == char_id:
                    versions.append({
                        "version": data["version"],
                        "timestamp": data["timestamp"],
                    })

        return versions
    
    def clear_cache(self) -> None:
        """キャッシュをクリア（モード切り替え時に使用）"""
        self.prompts.clear()


# Global repository instance
_repository: Optional[PromptRepository] = None


def get_prompt_manager(char_id: str, jetracer_mode: bool = False) -> PromptManager:
    """
    Get PromptManager for a character.
    
    Args:
        char_id: Character ID ("A", "B", or "director")
        jetracer_mode: True for JetRacer mode, False for general conversation
    """
    global _repository
    if _repository is None:
        _repository = PromptRepository()
    return _repository.get_manager(char_id, jetracer_mode=jetracer_mode)


def get_prompt_repository() -> PromptRepository:
    """Get global prompt repository"""
    global _repository
    if _repository is None:
        _repository = PromptRepository()
    return _repository
