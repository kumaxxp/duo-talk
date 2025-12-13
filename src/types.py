"""
Data types and models for the commentary system.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime


class DirectorStatus(str, Enum):
    """Director evaluation status"""
    PASS = "PASS"
    RETRY = "RETRY"
    MODIFY = "MODIFY"


class Speaker(str, Enum):
    """Character speaker identifier"""
    SISTER = "A"  # 姉 (Elder Sister)
    SISTER_NAME = "Elder Sister"
    BROTHER = "B"  # 妹 (Younger Sister) - using "Brother" for clarity in context
    BROTHER_NAME = "Younger Sister"


@dataclass
class CharacterConfig:
    """Character configuration"""
    name: str
    system_prompt: str
    domains: List[str]  # e.g., ["tourism", "action", "phenomena"]
    tone_markers: List[str]  # e.g., ["〜ね", "〜だよ"]
    id: str = field(default="A")


@dataclass
class DirectorEvaluation:
    """Director's evaluation of a response"""
    status: DirectorStatus
    reason: str
    suggestion: Optional[str] = None
    confidence: float = 0.8


@dataclass
class Turn:
    """Single turn of dialogue"""
    turn_num: int
    frame_num: int
    speaker: str  # "A" or "B"
    text: str
    raw_text: Optional[str] = None  # Before post-processing
    director_instruction: Optional[str] = None
    rag_hints: List[str] = field(default_factory=list)
    evaluation: Optional[DirectorEvaluation] = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Frame:
    """Input frame (image/video description)"""
    frame_num: int
    description: str
    image_path: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Commentary:
    """Complete commentary session"""
    run_id: str
    frames: List[Frame]
    turns: List[Turn] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ValidationResult:
    """Validation result for a response"""
    is_valid: bool
    language_check: bool  # Japanese only
    tone_check: bool  # Character tone consistency
    consistency_check: bool  # Logical consistency
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
