"""
Configuration management for the commentary system.
"""

import os
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        pass


class Config:
    """Global configuration"""

    def __init__(self):
        load_dotenv(override=False)

        # LLM Configuration
        self.openai_base_url = os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "not-needed")
        self.openai_model = os.getenv("OPENAI_MODEL", "mistral")

        # Character Configuration
        self.max_turns = int(os.getenv("MAX_TURNS", "5"))
        self.temperature = float(os.getenv("TEMPERATURE", "0.7"))
        self.max_tokens = int(os.getenv("MAX_TOKENS", "400"))

        # System Configuration
        # 大きなモデル（Qwen 32B等）では応答に時間がかかるため、デフォルト60秒に設定
        self.timeout = int(os.getenv("TIMEOUT", "60"))
        self.log_dir = Path(os.getenv("LOG_DIR", "runs"))
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Project paths
        self.project_root = Path(__file__).parent.parent
        self.persona_dir = self.project_root / "persona"
        self.rag_data_dir = self.project_root / "rag_data"

    def get_persona_path(self, char_id: str) -> Path:
        """Get system prompt path for a character"""
        return self.persona_dir / f"{char_id}.prompt.txt"

    def get_rag_domain_path(self, char_id: str) -> Path:
        """Get RAG domain data path for a character"""
        return self.rag_data_dir / f"char_{char_id}_domain"

    def validate(self) -> bool:
        """Validate critical configuration"""
        required_paths = [
            self.persona_dir / "char_a.prompt.txt",
            self.persona_dir / "char_b.prompt.txt",
            self.persona_dir / "director.prompt.txt",
        ]

        for path in required_paths:
            if not path.exists():
                print(f"Warning: Missing {path}")
                return False
        return True


# Global config instance
config = Config()
