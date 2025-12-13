"""
JSONL logging for commentary sessions.
"""

import json
from pathlib import Path
from typing import Any, Dict
from datetime import datetime

from src.config import config


class Logger:
    """JSONL logger for commentary events"""

    def __init__(self, log_dir: Path = None):
        self.log_dir = log_dir or config.log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "commentary_runs.jsonl"

    def log_event(self, event: Dict[str, Any]) -> None:
        """
        Log an event to JSONL file.

        Args:
            event: Event dictionary with at least 'event' key
        """
        # Add timestamp if not present
        if "timestamp" not in event:
            event["timestamp"] = datetime.now().isoformat()

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def log_turn(
        self,
        run_id: str,
        turn_num: int,
        frame_num: int,
        speaker: str,
        text: str,
        director_instruction: str = None,
        rag_hints: list = None,
    ) -> None:
        """Log a dialogue turn"""
        self.log_event({
            "event": "turn",
            "run_id": run_id,
            "turn": turn_num,
            "frame": frame_num,
            "speaker": speaker,
            "text": text,
            "director_instruction": director_instruction,
            "rag_hints": rag_hints or [],
        })

    def log_director_check(
        self,
        run_id: str,
        turn_num: int,
        speaker: str,
        status: str,
        reason: str,
        suggestion: str = None,
    ) -> None:
        """Log director evaluation"""
        self.log_event({
            "event": "director_check",
            "run_id": run_id,
            "turn": turn_num,
            "speaker": speaker,
            "status": status,
            "reason": reason,
            "suggestion": suggestion,
        })

    def log_validation(
        self,
        run_id: str,
        turn_num: int,
        speaker: str,
        is_valid: bool,
        issues: list = None,
    ) -> None:
        """Log validation result"""
        self.log_event({
            "event": "validation",
            "run_id": run_id,
            "turn": turn_num,
            "speaker": speaker,
            "is_valid": is_valid,
            "issues": issues or [],
        })

    def log_run_start(
        self,
        run_id: str,
        frame_count: int,
        metadata: dict = None,
    ) -> None:
        """Log session start"""
        self.log_event({
            "event": "run_start",
            "run_id": run_id,
            "frame_count": frame_count,
            "metadata": metadata or {},
        })

    def log_run_end(self, run_id: str, total_turns: int) -> None:
        """Log session end"""
        self.log_event({
            "event": "run_end",
            "run_id": run_id,
            "total_turns": total_turns,
        })

    def log_error(self, run_id: str, turn_num: int, message: str) -> None:
        """Log error"""
        self.log_event({
            "event": "error",
            "run_id": run_id,
            "turn": turn_num,
            "message": message,
        })


# Global logger instance
_logger: Logger = None


def get_logger() -> Logger:
    """Get or create global logger"""
    global _logger
    if _logger is None:
        _logger = Logger()
    return _logger
