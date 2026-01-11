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
    WARN = "WARN"
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


class BeatStage(str, Enum):
    """Beat stage in dialogue progression"""
    SETUP = "SETUP"
    EXPLORATION = "EXPLORATION"
    PERSONAL = "PERSONAL"
    WRAP_UP = "WRAP_UP"


class DialoguePattern(str, Enum):
    """Dialogue pattern types"""
    A = "A"  # 発見→補足
    B = "B"  # 疑問→解説
    C = "C"  # 誤解→訂正
    D = "D"  # 脱線→修正
    E = "E"  # 共感→発展


@dataclass
class TopicState:
    """話題の状態管理（Director v3）"""
    focus_hook: str = ""                    # 現在の話題（1つ）
    hook_depth: int = 0                     # 深掘り段階 (0-3)
    depth_step: str = "DISCOVER"            # "DISCOVER" | "SURFACE" | "WHY" | "EXPAND"
    turns_on_hook: int = 0                  # このhookで何ターン経過
    forbidden_topics: List[str] = field(default_factory=list)  # 禁止トピック
    must_include: List[str] = field(default_factory=list)      # 必須ワード

    def advance_depth(self):
        """深掘り段階を進める"""
        self.turns_on_hook += 1
        if self.hook_depth < 3:
            self.hook_depth += 1

        depth_steps = ["DISCOVER", "SURFACE", "WHY", "EXPAND"]
        self.depth_step = depth_steps[min(self.hook_depth, 3)]

    def can_switch_topic(self) -> bool:
        """話題転換が許可されるか"""
        # Relaxed condition: Allow switch after at least 1 turn on the hook
        # Original was depth >= 2 or turns >= 3
        return self.turns_on_hook >= 1

    def switch_topic(self, new_hook: str):
        """話題を転換"""
        if self.focus_hook:
            self.forbidden_topics.append(self.focus_hook)
            # 禁止リストは最大5個まで
            self.forbidden_topics = self.forbidden_topics[-5:]

        self.focus_hook = new_hook
        self.hook_depth = 0
        self.depth_step = "DISCOVER"
        self.turns_on_hook = 0
        self.must_include = [new_hook]

    def reset(self):
        """状態をリセット（新しいナレーション開始時）"""
        self.focus_hook = ""
        self.hook_depth = 0
        self.depth_step = "DISCOVER"
        self.turns_on_hook = 0
        self.forbidden_topics = []
        self.must_include = []


@dataclass
class DirectorEvaluation:
    """Director's evaluation of a response"""
    status: DirectorStatus
    reason: str
    suggestion: Optional[str] = None
    confidence: float = 0.8
    # New fields for dialogue orchestration
    next_pattern: Optional[str] = None  # "A", "B", "C", "D", "E"
    next_instruction: Optional[str] = None  # Specific instruction for next speaker
    beat_stage: Optional[str] = None  # "SETUP", "EXPLORATION", "PERSONAL", "WRAP_UP"
    # Director v2 fields for NOOP support and misfire prevention
    action: str = "NOOP"  # "NOOP" or "INTERVENE"
    hook: Optional[str] = None  # Concrete noun phrase triggering intervention
    evidence: Optional[Dict[str, Any]] = None  # {"dialogue": str|None, "frame": str|None}
    # Director v3 fields for Topic Manager
    focus_hook: Optional[str] = None          # 現在の話題（常に出力）
    hook_depth: int = 0                        # 深掘り段階
    depth_step: str = "DISCOVER"               # 深掘りステップ名
    turns_on_hook: int = 0                     # このhookで何ターン経過
    forbidden_topics: List[str] = field(default_factory=list)  # 禁止トピック
    must_include: List[str] = field(default_factory=list)      # 必須ワード
    character_role: str = ""                   # キャラクターに期待する役割
    # Director v3 fields for NoveltyGuard
    novelty_info: Optional[Dict[str, Any]] = None  # NoveltyGuard check result


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
