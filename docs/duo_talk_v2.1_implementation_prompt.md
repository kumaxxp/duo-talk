# duo-talk v2.1 実装指示プロンプト

## 概要

duo-talkシステムのv2.1アップデートを実装する。主な変更点は以下の通り：

1. **DuoSignals**: スレッドセーフな状態管理（event append + snapshot + lock方式）
2. **Injection優先度**: 直前発言の位置修正 + スロット強制注入
3. **NoveltyGuard**: 話題変更ではなく「同トピック内の切り口変更」
4. **SilenceController**: 沈黙をLLM生成ではなくUI層で制御
5. **世界設定の固定注入**: 姉妹共同行動ルール

## 前提条件

- 既存のduo-talkプロジェクトのディレクトリ構造を確認すること
- Python 3.10以上を想定
- 依存ライブラリ: dataclasses, threading, copy, enum, re, yaml, typing

---

## Phase 1A: DuoSignals（スレッドセーフ版）

### 新規作成: `src/signals.py`

```python
"""
duo-talk v2.1 - DuoSignals
スレッドセーフな状態管理システム

設計方針：
- シングルトンパターンで全体から参照可能
- threading.RLock で並列アクセスを保護
- update() でイベントとして状態を更新（書き込み）
- snapshot() でdeepcopyを返す（読み出し）
- 直接属性を触らせない
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from copy import deepcopy
from enum import Enum


class EventType(Enum):
    """イベントタイプ"""
    SENSOR = "sensor"
    VLM = "vlm"
    CONVERSATION = "conversation"
    RUN_RESULT = "run_result"
    MODE_CHANGE = "mode_change"


@dataclass
class SignalEvent:
    """イベント単位での状態変更"""
    event_type: EventType
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        if isinstance(self.event_type, str):
            self.event_type = EventType(self.event_type)


@dataclass
class DuoSignalsState:
    """姉妹間で共有する状態（内部データ）"""
    
    # === 走行状態 ===
    jetracer_mode: str = "SENSOR_ONLY"  # SENSOR_ONLY, VISION, FULL_AUTONOMY
    current_speed: float = 0.0
    steering_angle: float = 0.0
    distance_sensors: Dict[str, float] = field(default_factory=dict)
    
    # === VLM観測 ===
    scene_facts: Dict[str, str] = field(default_factory=dict)
    scene_timestamp: Optional[datetime] = None
    
    # === 会話状態 ===
    last_speaker: str = ""  # "yana" or "ayu"
    turn_count: int = 0
    current_topic: str = ""
    
    # === ループ検知用 ===
    recent_topics: List[str] = field(default_factory=list)
    topic_depth: int = 0
    unfilled_slots: List[str] = field(default_factory=list)
    
    # === 短期記憶 ===
    recent_events: List[Dict[str, Any]] = field(default_factory=list)
    
    # === タイムスタンプ ===
    last_updated: datetime = field(default_factory=datetime.now)


class DuoSignals:
    """
    スレッドセーフな状態管理（シングルトン）
    
    使用方法:
        signals = DuoSignals()
        
        # 書き込み（イベントとして）
        signals.update(SignalEvent(
            event_type=EventType.SENSOR,
            data={"sensors": {"left": 0.5, "right": 0.6}, "speed": 1.2}
        ))
        
        # 読み出し（スナップショット）
        state = signals.snapshot()
        print(state.current_speed)
    """
    
    _instance: Optional['DuoSignals'] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> 'DuoSignals':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._state = DuoSignalsState()
                    instance._event_log: List[SignalEvent] = []
                    instance._state_lock = threading.RLock()
                    cls._instance = instance
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """テスト用: シングルトンインスタンスをリセット"""
        with cls._lock:
            cls._instance = None
    
    def update(self, event: SignalEvent) -> None:
        """
        イベントとして状態を更新（書き込み）
        
        Args:
            event: SignalEvent オブジェクト
        """
        with self._state_lock:
            # イベントログに追加
            self._event_log.append(event)
            if len(self._event_log) > 100:
                self._event_log.pop(0)
            
            # イベントタイプに応じて状態を更新
            self._apply_event(event)
            
            # タイムスタンプ更新
            self._state.last_updated = datetime.now()
    
    def _apply_event(self, event: SignalEvent) -> None:
        """イベントを状態に適用"""
        data = event.data
        
        if event.event_type == EventType.SENSOR:
            if "sensors" in data:
                self._state.distance_sensors = data["sensors"]
            if "speed" in data:
                self._state.current_speed = data["speed"]
            if "steering" in data:
                self._state.steering_angle = data["steering"]
        
        elif event.event_type == EventType.VLM:
            if "facts" in data:
                self._state.scene_facts = data["facts"]
            self._state.scene_timestamp = event.timestamp
        
        elif event.event_type == EventType.CONVERSATION:
            if "speaker" in data:
                self._state.last_speaker = data["speaker"]
            self._state.turn_count += 1
            
            if "topic" in data:
                topic = data["topic"]
                self._state.current_topic = topic
                self._state.recent_topics.append(topic)
                if len(self._state.recent_topics) > 10:
                    self._state.recent_topics.pop(0)
                
                # トピック深度の更新
                if len(self._state.recent_topics) >= 2:
                    if self._state.recent_topics[-1] == self._state.recent_topics[-2]:
                        self._state.topic_depth += 1
                    else:
                        self._state.topic_depth = 1
            
            if "unfilled_slots" in data:
                self._state.unfilled_slots = data["unfilled_slots"]
        
        elif event.event_type == EventType.RUN_RESULT:
            event_data = {
                "type": data.get("type", "unknown"),
                "timestamp": event.timestamp,
                "details": data.get("details", {})
            }
            self._state.recent_events.append(event_data)
            if len(self._state.recent_events) > 5:
                self._state.recent_events.pop(0)
        
        elif event.event_type == EventType.MODE_CHANGE:
            if "mode" in data:
                self._state.jetracer_mode = data["mode"]
    
    def snapshot(self) -> DuoSignalsState:
        """
        現在の状態のスナップショットを取得（読み出し）
        
        Returns:
            DuoSignalsState: 状態のディープコピー
        """
        with self._state_lock:
            return deepcopy(self._state)
    
    def is_stale(self, max_age_seconds: float = 2.0) -> bool:
        """
        情報が古いかどうか
        
        Args:
            max_age_seconds: 許容する最大経過時間（秒）
        
        Returns:
            bool: 情報が古い場合True
        """
        with self._state_lock:
            age = (datetime.now() - self._state.last_updated).total_seconds()
            return age > max_age_seconds
    
    def get_recent_events(self, event_type: Optional[EventType] = None, limit: int = 10) -> List[SignalEvent]:
        """
        最近のイベントログを取得
        
        Args:
            event_type: フィルタするイベントタイプ（Noneなら全て）
            limit: 取得する最大件数
        
        Returns:
            List[SignalEvent]: イベントのリスト
        """
        with self._state_lock:
            events = self._event_log.copy()
            if event_type:
                events = [e for e in events if e.event_type == event_type]
            return events[-limit:]
```

---

## Phase 1B: Injection優先度システム

### 新規作成: `src/injection.py`

```python
"""
duo-talk v2.1 - Injection Priority System
プロンプトへの情報注入を優先度で管理

設計方針：
- 優先度が低い数字ほど先に配置（文脈として早く）
- LAST_UTTERANCE は HISTORY の直後（55）に配置
- スロット未充足時は強制注入
"""

from dataclasses import dataclass, field
from typing import List, Optional, Set, Dict, Any
from enum import IntEnum


class Priority(IntEnum):
    """注入優先度（低い数字 = 先に配置）"""
    SYSTEM = 10              # システムプロンプト（固定）
    WORLD_RULES = 15         # 姉妹共同行動ルール（固定）
    DEEP_VALUES = 20         # キャラクター深層設定（短く）
    LONG_MEMORY = 30         # 長期記憶（姉妹の共有体験）
    RAG = 40                 # RAG知識
    HISTORY = 50             # 会話履歴
    LAST_UTTERANCE = 55      # 直前の相手の発言（HISTORYの直後）
    SHORT_MEMORY = 60        # 短期記憶（最近のイベント）
    SCENE_FACTS = 65         # VLM観測
    WORLD_STATE = 70         # 現在の走行状態
    SLOT_FILLER = 75         # 未充足スロットの強制注入
    DIRECTOR = 80            # ディレクター指示
    FEW_SHOT = 85            # Few-shot例（状況トリガー）


@dataclass
class PromptInjection:
    """プロンプトへの情報注入"""
    text: str
    priority: int
    source: str = ""
    slot_type: Optional[str] = None  # 充足するスロットタイプ
    
    def __post_init__(self):
        if isinstance(self.priority, Priority):
            self.priority = int(self.priority)


# 情報スロット定義
SLOT_DEFINITIONS = {
    "具体性": {
        "description": "具体的な数値・場所・エピソード",
        "indicators": ["数値", "m/s", "秒", "回", "コーナー", "位置", "前に", "あの時"],
        "injection_template": (
            "【必須】現在の話題について、以下のいずれかを1つ以上含めること：\n"
            "- 具体的な数値（速度、距離、時間、回数）\n"
            "- 具体的な場所や位置（どのコーナー、どの区間）\n"
            "- 過去の具体的なエピソード"
        )
    },
    "関係性": {
        "description": "姉妹が一緒にいることが分かる要素",
        "indicators": ["私たち", "うちら", "二人で", "一緒に", "姉様に", "あゆに"],
        "injection_template": (
            "【必須】姉妹が「一緒にいる」ことが分かる要素を含めること：\n"
            "- 「私たち」「うちら」など共同表現\n"
            "- 相手への依頼や確認\n"
            "- 役割分担の言及"
        )
    },
    "非対称性": {
        "description": "姉妹の役割の違いが分かる要素",
        "indicators": ["感覚", "データ", "計算", "直感", "分析", "数字"],
        "injection_template": (
            "【推奨】姉妹の役割の違いを活かすこと：\n"
            "- やな：感覚や直感での判断・発見\n"
            "- あゆ：データや数値での補足・分析"
        )
    }
}


class SlotChecker:
    """スロット充足チェッカー"""
    
    def __init__(self):
        self.filled_slots: Set[str] = set()
    
    def check_text(self, text: str) -> Set[str]:
        """テキストから充足されたスロットを検出"""
        filled = set()
        for slot_name, slot_def in SLOT_DEFINITIONS.items():
            for indicator in slot_def["indicators"]:
                if indicator in text:
                    filled.add(slot_name)
                    break
        return filled
    
    def update(self, text: str) -> None:
        """テキストでスロット充足状態を更新"""
        self.filled_slots.update(self.check_text(text))
    
    def get_unfilled(self, required: Optional[List[str]] = None) -> List[str]:
        """未充足スロットを取得"""
        if required is None:
            required = ["具体性"]  # デフォルトで具体性は必須
        return [s for s in required if s not in self.filled_slots]
    
    def reset(self) -> None:
        """リセット（新しいターンの開始時）"""
        self.filled_slots.clear()


class PromptBuilder:
    """
    優先度に基づいてプロンプトを組み立てる
    
    使用方法:
        builder = PromptBuilder()
        builder.add("システムプロンプト", Priority.SYSTEM, "system")
        builder.add("会話履歴", Priority.HISTORY, "history")
        builder.add("直前の発言", Priority.LAST_UTTERANCE, "last_utterance")
        
        # スロットチェック
        builder.check_and_inject_slots("センサー")
        
        prompt = builder.build()
    """
    
    def __init__(self, max_tokens: int = 6000):
        self.injections: List[PromptInjection] = []
        self.max_tokens = max_tokens
        self.slot_checker = SlotChecker()
    
    def add(
        self, 
        text: str, 
        priority: int, 
        source: str = "",
        slot_type: Optional[str] = None
    ) -> None:
        """
        プロンプト要素を追加
        
        Args:
            text: 注入するテキスト
            priority: 優先度（Priority enumまたはint）
            source: デバッグ用のソース名
            slot_type: この要素が充足するスロットタイプ
        """
        if isinstance(priority, Priority):
            priority = int(priority)
        
        self.injections.append(PromptInjection(text, priority, source, slot_type))
        
        # スロット充足をチェック
        if slot_type:
            self.slot_checker.filled_slots.add(slot_type)
        self.slot_checker.update(text)
    
    def check_and_inject_slots(
        self, 
        current_topic: str,
        required_slots: Optional[List[str]] = None,
        topic_depth: int = 0
    ) -> List[str]:
        """
        未充足スロットがあれば強制注入
        
        Args:
            current_topic: 現在の話題
            required_slots: 必須スロットのリスト
            topic_depth: 同じ話題の継続ターン数
        
        Returns:
            List[str]: 注入されたスロットのリスト
        """
        if required_slots is None:
            required_slots = ["具体性"]
            # 3ターン以上同じ話題なら関係性も要求
            if topic_depth >= 3:
                required_slots.append("関係性")
        
        unfilled = self.slot_checker.get_unfilled(required_slots)
        
        for slot_name in unfilled:
            if slot_name in SLOT_DEFINITIONS:
                template = SLOT_DEFINITIONS[slot_name]["injection_template"]
                injection_text = f"{template}\n（現在の話題: {current_topic}）"
                self.add(
                    injection_text, 
                    Priority.SLOT_FILLER, 
                    f"slot_filler_{slot_name}"
                )
        
        return unfilled
    
    def build(self, include_debug: bool = False) -> str:
        """
        プロンプトを組み立てる
        
        Args:
            include_debug: デバッグ情報を含めるか
        
        Returns:
            str: 組み立てられたプロンプト
        """
        # 優先度でソート（低い順）
        sorted_injections = sorted(self.injections, key=lambda x: x.priority)
        
        if include_debug:
            parts = []
            for inj in sorted_injections:
                parts.append(f"<!-- [{inj.priority}] {inj.source} -->\n{inj.text}")
            return "\n\n".join(parts)
        else:
            return "\n\n".join([inj.text for inj in sorted_injections])
    
    def get_structure(self) -> List[Dict[str, Any]]:
        """デバッグ用: プロンプト構造を取得"""
        sorted_injections = sorted(self.injections, key=lambda x: x.priority)
        return [
            {
                "priority": inj.priority,
                "source": inj.source,
                "slot_type": inj.slot_type,
                "length": len(inj.text)
            }
            for inj in sorted_injections
        ]
    
    def reset(self) -> None:
        """ビルダーをリセット"""
        self.injections.clear()
        self.slot_checker.reset()
```

---

## Phase 1C: NoveltyGuard（同トピック内変化版）

### 新規作成: `src/novelty_guard.py`

```python
"""
duo-talk v2.1 - NoveltyGuard
話題ループを検知し、同トピック内で切り口を変える

設計方針：
- 話題を変更するのではなく、同じ話題の切り口を変える
- 直近で使った戦略は避ける（バリエーション確保）
- 具体性・対立・行動・過去参照の4戦略
"""

from typing import List, Set, Dict, Optional, Any
from enum import Enum
from dataclasses import dataclass, field
import re


class LoopBreakStrategy(Enum):
    """ループ脱出戦略（話題変更ではなく切り口変更）"""
    FORCE_SPECIFIC_SLOT = "specific_slot"      # 具体スロット要求
    FORCE_CONFLICT_WITHIN = "conflict_within"  # 同トピ内の対立
    FORCE_ACTION_NEXT = "action_next"          # 次の行動を決める
    FORCE_PAST_REFERENCE = "past_reference"    # 過去の具体的エピソード
    NOOP = "noop"                              # 介入なし


@dataclass
class LoopCheckResult:
    """ループ検知結果"""
    loop_detected: bool = False
    stuck_nouns: List[str] = field(default_factory=list)
    strategy: LoopBreakStrategy = LoopBreakStrategy.NOOP
    injection: Optional[str] = None
    topic_depth: int = 0


class NoveltyGuard:
    """
    話題ループを検知し、同トピック内で切り口を変える
    
    使用方法:
        guard = NoveltyGuard()
        
        # 各ターンで呼び出し
        result = guard.check_and_update(character_response)
        
        if result.loop_detected:
            # result.injection をプロンプトに追加
            builder.add(result.injection, Priority.DIRECTOR, "novelty_guard")
    """
    
    def __init__(self, max_topic_depth: int = 3):
        """
        Args:
            max_topic_depth: ループと判定するまでの同一話題ターン数
        """
        self.max_topic_depth = max_topic_depth
        self.recent_nouns: List[Set[str]] = []
        self.recent_strategies: List[LoopBreakStrategy] = []
        
        # 除外する一般的な名詞
        self.stop_nouns = {
            "こと", "もの", "ところ", "とき", "ため", "よう",
            "それ", "これ", "あれ", "どれ", "ここ", "そこ",
            "私", "あなた", "姉様", "方", "人", "今", "前",
        }
    
    def extract_nouns(self, text: str) -> Set[str]:
        """
        テキストから名詞を抽出
        
        Note: 本番環境ではMeCab等での形態素解析を推奨
        """
        # カタカナ・漢字の連続を抽出
        nouns = set(re.findall(r'[ァ-ヶー]{2,}|[一-龯]{2,}', text))
        
        # 短すぎる名詞と一般的な名詞を除外
        nouns = {n for n in nouns if len(n) >= 2 and n not in self.stop_nouns}
        
        return nouns
    
    def check_and_update(self, text: str) -> LoopCheckResult:
        """
        ループ検知して結果を返す
        
        Args:
            text: チェックするテキスト（直近の発言）
        
        Returns:
            LoopCheckResult: 検知結果
        """
        current_nouns = self.extract_nouns(text)
        
        result = LoopCheckResult()
        
        if len(self.recent_nouns) >= self.max_topic_depth:
            overlap_count = 0
            common_nouns = current_nouns.copy()
            
            for past_nouns in self.recent_nouns[-self.max_topic_depth:]:
                intersection = current_nouns & past_nouns
                if intersection:
                    overlap_count += 1
                    common_nouns &= past_nouns
            
            result.topic_depth = overlap_count
            
            if overlap_count >= self.max_topic_depth and common_nouns:
                result.loop_detected = True
                result.stuck_nouns = list(common_nouns)[:5]  # 最大5つ
                result.strategy = self._select_strategy()
                result.injection = self._generate_injection(
                    result.strategy,
                    result.stuck_nouns
                )
        
        # 履歴更新
        self.recent_nouns.append(current_nouns)
        if len(self.recent_nouns) > 10:
            self.recent_nouns.pop(0)
        
        return result
    
    def _select_strategy(self) -> LoopBreakStrategy:
        """戦略を選択（直近で使った戦略は避ける）"""
        strategies = [
            LoopBreakStrategy.FORCE_SPECIFIC_SLOT,
            LoopBreakStrategy.FORCE_CONFLICT_WITHIN,
            LoopBreakStrategy.FORCE_ACTION_NEXT,
            LoopBreakStrategy.FORCE_PAST_REFERENCE,
        ]
        
        # 直近2回で使った戦略は避ける
        recent_set = set(self.recent_strategies[-2:]) if self.recent_strategies else set()
        
        for strategy in strategies:
            if strategy not in recent_set:
                self.recent_strategies.append(strategy)
                if len(self.recent_strategies) > 10:
                    self.recent_strategies.pop(0)
                return strategy
        
        # 全部使った場合は最初の戦略
        self.recent_strategies.append(strategies[0])
        return strategies[0]
    
    def _generate_injection(
        self, 
        strategy: LoopBreakStrategy, 
        stuck_nouns: List[str]
    ) -> str:
        """戦略に応じた注入プロンプトを生成"""
        topic = "、".join(stuck_nouns[:3]) if stuck_nouns else "現在の話題"
        
        injections = {
            LoopBreakStrategy.FORCE_SPECIFIC_SLOT: (
                f"【切り口変更：具体化】「{topic}」について、具体的な情報を1つ追加すること：\n"
                "- 数値（速度、距離、時間、温度、回数など）\n"
                "- 場所（どのコーナー、どの位置、どの区間）\n"
                "- 過去の具体的な出来事（「前に〜した」「あの時〜だった」）"
            ),
            LoopBreakStrategy.FORCE_CONFLICT_WITHIN: (
                f"【切り口変更：意見対立】「{topic}」について、姉妹で意見が分かれる点を出すこと：\n"
                "- やな：直感や感覚での判断（「なんか〜な気がする」）\n"
                "- あゆ：データや数値での根拠（「数値では〜です」）\n"
                "※ 軽い対立 → 妥協 or 決着の流れで"
            ),
            LoopBreakStrategy.FORCE_ACTION_NEXT: (
                f"【切り口変更：次の行動】「{topic}」の話を踏まえて、次に何をするか決めること：\n"
                "- 次の走行でどう変えるか\n"
                "- 設定やパラメータを調整するか\n"
                "- 休憩、確認、準備をするか\n"
                "※ 具体的なアクションを決める"
            ),
            LoopBreakStrategy.FORCE_PAST_REFERENCE: (
                f"【切り口変更：過去参照】「{topic}」に関連する過去の出来事を参照すること：\n"
                "- 「前に似たことがあった」\n"
                "- 「あの時は失敗/成功した」\n"
                "- 「そこから学んだことを活かす」\n"
                "※ 具体的な過去のエピソードを出す"
            ),
        }
        
        return injections.get(strategy, "")
    
    def reset(self) -> None:
        """状態をリセット（新しいセッション開始時）"""
        self.recent_nouns.clear()
        self.recent_strategies.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """統計情報を取得"""
        return {
            "history_length": len(self.recent_nouns),
            "recent_strategies": [s.value for s in self.recent_strategies[-5:]],
            "current_nouns": list(self.recent_nouns[-1]) if self.recent_nouns else []
        }
```

---

## Phase 1D: SilenceController

### 新規作成: `src/silence_controller.py`

```python
"""
duo-talk v2.1 - SilenceController
沈黙をLLM生成ではなくUI層で制御

設計方針：
- 沈黙はLLMに「...」を生成させない
- action="SILENCE" を返してUI層で演出
- 難コーナー、高速区間、走行直後に適用
"""

from enum import Enum
from typing import Optional, Any
from dataclasses import dataclass
from datetime import datetime


class SilenceType(Enum):
    """沈黙タイプ"""
    TENSION = "tension"          # 緊張シーン（難コーナー）
    CONCENTRATION = "focus"      # 集中シーン（高速区間）
    AFTERMATH = "aftermath"      # 余韻（成功/失敗直後）
    THINKING = "thinking"        # 考え中


@dataclass
class SilenceAction:
    """沈黙アクション（LLM出力ではなくUI制御用）"""
    silence_type: SilenceType
    duration_seconds: float
    allow_short_utterance: bool = False  # 短い息遣い/感嘆のみ許可
    suggested_sfx: Optional[str] = None  # 効果音の提案
    suggested_bgm_intensity: float = 1.0  # BGM強度（0.0-1.0）
    
    def to_dict(self) -> dict:
        return {
            "type": "silence",
            "silence_type": self.silence_type.value,
            "duration": self.duration_seconds,
            "allow_short": self.allow_short_utterance,
            "sfx": self.suggested_sfx,
            "bgm_intensity": self.suggested_bgm_intensity
        }


class SilenceController:
    """
    沈黙判定を行い、LLMではなくUI層に指示を出す
    
    使用方法:
        controller = SilenceController()
        state = signals.snapshot()
        
        silence = controller.should_silence(state)
        if silence:
            # LLM生成をスキップし、UI層で沈黙演出
            return silence.to_dict()
    """
    
    def __init__(
        self,
        high_speed_threshold: float = 2.5,
        aftermath_window_seconds: float = 1.5
    ):
        """
        Args:
            high_speed_threshold: 高速とみなす速度閾値 (m/s)
            aftermath_window_seconds: 走行結果後の余韻時間 (秒)
        """
        self.high_speed_threshold = high_speed_threshold
        self.aftermath_window_seconds = aftermath_window_seconds
    
    def should_silence(self, signals_state: Any) -> Optional[SilenceAction]:
        """
        沈黙すべきかを判定
        
        Args:
            signals_state: DuoSignalsState のスナップショット
        
        Returns:
            SilenceAction if 沈黙すべき, None otherwise
        """
        scene = getattr(signals_state, 'scene_facts', {})
        speed = getattr(signals_state, 'current_speed', 0.0)
        recent_events = getattr(signals_state, 'recent_events', [])
        
        # 1. 難コーナー接近時
        upcoming = scene.get("upcoming", "")
        if upcoming in ["difficult_corner", "sharp_turn", "hairpin"]:
            return SilenceAction(
                silence_type=SilenceType.TENSION,
                duration_seconds=3.0,
                allow_short_utterance=True,
                suggested_sfx="engine_intense",
                suggested_bgm_intensity=0.3
            )
        
        # 2. 高速区間
        if speed > self.high_speed_threshold:
            return SilenceAction(
                silence_type=SilenceType.CONCENTRATION,
                duration_seconds=2.0,
                allow_short_utterance=False,
                suggested_sfx="wind_rush",
                suggested_bgm_intensity=0.5
            )
        
        # 3. 走行終了直後（成功/失敗問わず）
        if recent_events:
            last_event = recent_events[-1]
            event_type = last_event.get("type", "")
            event_time = last_event.get("timestamp")
            
            if event_type in ["success", "failure", "collision", "complete"]:
                if event_time:
                    if isinstance(event_time, datetime):
                        elapsed = (datetime.now() - event_time).total_seconds()
                    else:
                        elapsed = float('inf')
                    
                    if elapsed < self.aftermath_window_seconds:
                        return SilenceAction(
                            silence_type=SilenceType.AFTERMATH,
                            duration_seconds=1.5,
                            allow_short_utterance=True,
                            suggested_sfx="breath" if event_type == "success" else None,
                            suggested_bgm_intensity=0.7
                        )
        
        return None
    
    def get_short_utterances(self, silence_type: SilenceType, character: str) -> list:
        """
        沈黙中に許可される短い発話を取得
        
        Args:
            silence_type: 沈黙タイプ
            character: キャラクター名 ("yana" or "ayu")
        
        Returns:
            list: 許可される短い発話のリスト
        """
        utterances = {
            SilenceType.TENSION: {
                "yana": ["...", "っ", "ここ...", "くる..."],
                "ayu": ["...", "姉様...", "ここは..."]
            },
            SilenceType.CONCENTRATION: {
                "yana": [],  # 完全沈黙
                "ayu": []
            },
            SilenceType.AFTERMATH: {
                "yana": ["ふぅー...", "...っし！", "あー...", "..."],
                "ayu": ["...ふぅ", "...はい", "姉様...", "..."]
            },
            SilenceType.THINKING: {
                "yana": ["んー...", "えーと...", "あのさ..."],
                "ayu": ["そうですね...", "えっと...", "..."]
            }
        }
        
        return utterances.get(silence_type, {}).get(character, ["..."])
```

---

## Phase 1E: 世界設定ファイル

### 新規作成: `persona/world_rules.yaml`

```yaml
# duo-talk v2.1 - 世界設定（固定注入）
# この内容は PRIORITY_WORLD_RULES(15) で常に注入される

world_state:
  # === 絶対ルール ===
  core_rule: |
    【絶対ルール】やなとあゆは常に同じ場所・同じ状況を共有している。
    - 二人は同じJetRacerの走行をリアルタイムで観察している
    - センサー情報、カメラ映像、分析結果はすべて共有されている
    - 「私たち」「うちら」など共同表現を自然に使う
    - 片方だけが知っている情報は存在しない

  # === 空間的一体性 ===
  spatial_unity:
    description: "姉妹は物理的に同じ場所にいる"
    rules:
      - 物理的に同じ場所にいる（遠隔操作でも同じ画面を見ている）
      - 別々の行動をしていない
      - 「私は〜した」より「私たちは〜した」が自然
    examples:
      good:
        - "私たち、さっきのコーナーうまくいったね"
        - "あゆ、今の見た？"
        - "姉様、右センサーの値が..."
      bad:
        - "私は家でテレビを見てた"  # 別々の場所にいる
        - "あゆは何してたの？"  # 一緒にいるのに知らない

  # === 情報の対称性 ===
  information_symmetry:
    description: "情報は両者がリアルタイムで共有"
    rules:
      - センサー情報：両者がリアルタイムで把握
      - 分析結果：あゆが出したら即座にやなも把握
      - 走行状況：両者が同時に観察している
    note: |
      あゆが「分析した結果〜」と言ったとき、
      やなは「え、何？」と聞かない（既に共有されている）。
      やなは「おお、そうなんだ」や「それってつまり〜？」と反応する。

# === 会話の基本ルール ===
conversation_rules:
  - 相手の発言に必ず反応してから自分の話をする
  - 同じ内容の言い換えは避ける
  - 一般論より具体的な情報（数値、場所、エピソード）を優先
  - 説明的な長文より、会話らしい短いやり取りを重視
```

---

## Phase 2: 統合と既存コードの修正

### 修正対象: `src/character.py`（または既存のキャラクター生成モジュール）

以下の統合ポイントを実装してください：

```python
"""
既存のcharacter.pyへの統合例

主な変更点：
1. PromptBuilder を使ってプロンプトを組み立てる
2. NoveltyGuard でループ検知
3. SilenceController で沈黙判定
4. world_rules.yaml を固定注入
"""

import yaml
from pathlib import Path

from src.signals import DuoSignals, SignalEvent, EventType
from src.injection import PromptBuilder, Priority
from src.novelty_guard import NoveltyGuard
from src.silence_controller import SilenceController


class CharacterEngine:
    """キャラクター発話生成エンジン（v2.1統合版）"""
    
    def __init__(self, config_path: str = "config/duo_talk.yaml"):
        self.signals = DuoSignals()
        self.novelty_guard = NoveltyGuard()
        self.silence_controller = SilenceController()
        
        # 世界設定を読み込み
        world_rules_path = Path("persona/world_rules.yaml")
        if world_rules_path.exists():
            with open(world_rules_path, 'r', encoding='utf-8') as f:
                self.world_rules = yaml.safe_load(f)
        else:
            self.world_rules = {}
    
    def generate_response(
        self, 
        character: str,  # "yana" or "ayu"
        last_utterance: str,
        context: dict
    ) -> dict:
        """
        キャラクターの応答を生成
        
        Returns:
            dict: {
                "type": "speech" | "silence",
                "content": str (speech) | SilenceAction (silence),
                "debug": dict
            }
        """
        # 1. 状態のスナップショットを取得
        state = self.signals.snapshot()
        
        # 2. 沈黙判定
        silence = self.silence_controller.should_silence(state)
        if silence:
            return {
                "type": "silence",
                "content": silence.to_dict(),
                "debug": {"reason": "silence_controller"}
            }
        
        # 3. ループ検知
        loop_result = self.novelty_guard.check_and_update(last_utterance)
        
        # 4. プロンプト組み立て
        builder = PromptBuilder()
        
        # 4.1 システムプロンプト
        builder.add(
            self._get_system_prompt(),
            Priority.SYSTEM,
            "system"
        )
        
        # 4.2 世界設定（固定注入）
        if self.world_rules:
            core_rule = self.world_rules.get("world_state", {}).get("core_rule", "")
            if core_rule:
                builder.add(core_rule, Priority.WORLD_RULES, "world_rules")
        
        # 4.3 キャラクター設定
        builder.add(
            self._get_character_prompt(character),
            Priority.DEEP_VALUES,
            "character"
        )
        
        # 4.4 会話履歴
        if context.get("history"):
            builder.add(
                self._format_history(context["history"]),
                Priority.HISTORY,
                "history"
            )
        
        # 4.5 直前の発言（HISTORYの直後）
        builder.add(
            f"【直前の相手の発言】\n{last_utterance}",
            Priority.LAST_UTTERANCE,
            "last_utterance"
        )
        
        # 4.6 シーン情報
        if state.scene_facts:
            builder.add(
                f"【現在のシーン】\n{self._format_scene(state.scene_facts)}",
                Priority.SCENE_FACTS,
                "scene"
            )
        
        # 4.7 走行状態
        builder.add(
            self._format_world_state(state),
            Priority.WORLD_STATE,
            "world_state"
        )
        
        # 4.8 スロット充足チェック
        unfilled = builder.check_and_inject_slots(
            state.current_topic or "走行",
            topic_depth=state.topic_depth
        )
        
        # 4.9 ループ脱出指示
        if loop_result.loop_detected and loop_result.injection:
            builder.add(
                loop_result.injection,
                Priority.DIRECTOR,
                "novelty_guard"
            )
        
        # 5. プロンプト生成
        prompt = builder.build()
        
        # 6. LLM呼び出し（既存の実装を使用）
        response = self._call_llm(prompt, character)
        
        # 7. 会話イベントを記録
        self.signals.update(SignalEvent(
            event_type=EventType.CONVERSATION,
            data={
                "speaker": character,
                "topic": self._extract_topic(response)
            }
        ))
        
        return {
            "type": "speech",
            "content": response,
            "debug": {
                "loop_detected": loop_result.loop_detected,
                "strategy": loop_result.strategy.value if loop_result.loop_detected else None,
                "unfilled_slots": unfilled,
                "prompt_structure": builder.get_structure()
            }
        }
    
    def _get_system_prompt(self) -> str:
        """システムプロンプトを取得"""
        return """あなたはduo-talkシステムのキャラクターです。
JetRacer自動運転車の走行を実況・解説する姉妹AIの一人として振る舞ってください。

## 会話の基本ルール
- 相手の発言に必ず反応してから自分の話をする
- 同じ内容の言い換えは避ける
- 一般論より具体的な情報（数値、場所、エピソード）を優先
- 説明的な長文より、会話らしい短いやり取りを重視"""
    
    def _get_character_prompt(self, character: str) -> str:
        """キャラクタープロンプトを取得"""
        # 実際の実装では persona/char_a/ や persona/char_b/ から読み込む
        if character == "yana":
            return """## やな（姉/Edge AI）
- 発見役：「あ、なんか〜」「見て見て」
- 感覚表現：「なんか良い感じ」「ちょっと怖い」
- 口調：カジュアル、「〜じゃん」「〜でしょ」
- 判断基準：迷ったらとりあえず試す、数字より手応え"""
        else:
            return """## あゆ（妹/Cloud AI）
- 補足役：姉様の発見に数値や分析を付け加える
- 敬語ベース：ですます調だが堅すぎない
- やなを「姉様」と呼ぶ
- 判断基準：数字で裏付けてから判断、過去のログは宝"""
    
    def _format_history(self, history: list) -> str:
        """会話履歴をフォーマット"""
        lines = []
        for h in history[-5:]:  # 直近5ターン
            speaker = h.get("speaker", "?")
            content = h.get("content", "")
            lines.append(f"{speaker}: {content}")
        return "【会話履歴】\n" + "\n".join(lines)
    
    def _format_scene(self, scene_facts: dict) -> str:
        """シーン情報をフォーマット"""
        parts = []
        for key, value in scene_facts.items():
            parts.append(f"- {key}: {value}")
        return "\n".join(parts)
    
    def _format_world_state(self, state) -> str:
        """走行状態をフォーマット"""
        return f"""【現在の走行状態】
- モード: {state.jetracer_mode}
- 速度: {state.current_speed:.2f} m/s
- 舵角: {state.steering_angle:.1f}°
- センサー: {state.distance_sensors}"""
    
    def _extract_topic(self, text: str) -> str:
        """テキストから主要トピックを抽出（簡易版）"""
        # 実際の実装ではもっと高度な抽出を行う
        import re
        nouns = re.findall(r'[ァ-ヶー]{2,}|[一-龯]{2,}', text)
        return nouns[0] if nouns else "走行"
    
    def _call_llm(self, prompt: str, character: str) -> str:
        """LLMを呼び出して応答を生成（既存実装を使用）"""
        # 既存のLLM呼び出し処理をここに実装
        # vLLM, Ollama, OpenAI互換API等
        raise NotImplementedError("既存のLLM呼び出し処理を実装してください")
```

---

## テスト用コード

### 新規作成: `tests/test_v2_1_components.py`

```python
"""
duo-talk v2.1 コンポーネントテスト
"""

import pytest
from datetime import datetime, timedelta
import threading
import time


class TestDuoSignals:
    """DuoSignals のテスト"""
    
    def setup_method(self):
        from src.signals import DuoSignals
        DuoSignals.reset_instance()
    
    def test_singleton(self):
        from src.signals import DuoSignals
        s1 = DuoSignals()
        s2 = DuoSignals()
        assert s1 is s2
    
    def test_update_and_snapshot(self):
        from src.signals import DuoSignals, SignalEvent, EventType
        
        signals = DuoSignals()
        signals.update(SignalEvent(
            event_type=EventType.SENSOR,
            data={"speed": 1.5, "sensors": {"left": 0.3}}
        ))
        
        state = signals.snapshot()
        assert state.current_speed == 1.5
        assert state.distance_sensors == {"left": 0.3}
    
    def test_thread_safety(self):
        from src.signals import DuoSignals, SignalEvent, EventType
        
        signals = DuoSignals()
        errors = []
        
        def writer():
            for i in range(100):
                try:
                    signals.update(SignalEvent(
                        event_type=EventType.SENSOR,
                        data={"speed": float(i)}
                    ))
                except Exception as e:
                    errors.append(e)
        
        def reader():
            for _ in range(100):
                try:
                    state = signals.snapshot()
                    _ = state.current_speed
                except Exception as e:
                    errors.append(e)
        
        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0


class TestPromptBuilder:
    """PromptBuilder のテスト"""
    
    def test_priority_order(self):
        from src.injection import PromptBuilder, Priority
        
        builder = PromptBuilder()
        builder.add("Last", Priority.FEW_SHOT, "few_shot")
        builder.add("First", Priority.SYSTEM, "system")
        builder.add("Middle", Priority.HISTORY, "history")
        
        prompt = builder.build()
        assert prompt.index("First") < prompt.index("Middle") < prompt.index("Last")
    
    def test_last_utterance_after_history(self):
        from src.injection import PromptBuilder, Priority
        
        builder = PromptBuilder()
        builder.add("会話履歴", Priority.HISTORY, "history")
        builder.add("直前の発言", Priority.LAST_UTTERANCE, "last")
        builder.add("シーン情報", Priority.SCENE_FACTS, "scene")
        
        prompt = builder.build()
        # HISTORY(50) < LAST_UTTERANCE(55) < SCENE_FACTS(65)
        assert prompt.index("会話履歴") < prompt.index("直前の発言") < prompt.index("シーン情報")
    
    def test_slot_injection(self):
        from src.injection import PromptBuilder, Priority
        
        builder = PromptBuilder()
        builder.add("一般的な話", Priority.HISTORY, "history")
        
        # 具体性スロットが未充足
        unfilled = builder.check_and_inject_slots("センサー")
        
        assert "具体性" in unfilled
        prompt = builder.build()
        assert "【必須】" in prompt


class TestNoveltyGuard:
    """NoveltyGuard のテスト"""
    
    def test_no_loop_initially(self):
        from src.novelty_guard import NoveltyGuard
        
        guard = NoveltyGuard(max_topic_depth=3)
        result = guard.check_and_update("センサーの値が変です")
        
        assert result.loop_detected == False
    
    def test_loop_detection(self):
        from src.novelty_guard import NoveltyGuard, LoopBreakStrategy
        
        guard = NoveltyGuard(max_topic_depth=3)
        
        # 同じ名詞を含む発言を3回
        guard.check_and_update("センサーの値が変です")
        guard.check_and_update("センサーを確認しましょう")
        result = guard.check_and_update("センサーの調子が悪いかも")
        
        assert result.loop_detected == True
        assert "センサー" in result.stuck_nouns
        assert result.strategy != LoopBreakStrategy.NOOP
        assert result.injection is not None
    
    def test_strategy_rotation(self):
        from src.novelty_guard import NoveltyGuard
        
        guard = NoveltyGuard(max_topic_depth=2)
        strategies = []
        
        for i in range(6):
            guard.check_and_update(f"テスト{i}の話題")
            guard.check_and_update(f"テスト{i}について")
            result = guard.check_and_update(f"テスト{i}の件")
            if result.loop_detected:
                strategies.append(result.strategy)
            guard.reset()
        
        # 同じ戦略が連続しないことを確認
        for i in range(len(strategies) - 1):
            if strategies[i] == strategies[i + 1]:
                # 2回連続は許容（直近2回を避けるため）
                if i + 2 < len(strategies):
                    assert strategies[i] != strategies[i + 2]


class TestSilenceController:
    """SilenceController のテスト"""
    
    def test_high_speed_silence(self):
        from src.silence_controller import SilenceController, SilenceType
        from dataclasses import dataclass
        
        @dataclass
        class MockState:
            current_speed: float = 3.0
            scene_facts: dict = None
            recent_events: list = None
            
            def __post_init__(self):
                self.scene_facts = self.scene_facts or {}
                self.recent_events = self.recent_events or []
        
        controller = SilenceController(high_speed_threshold=2.5)
        state = MockState(current_speed=3.0)
        
        result = controller.should_silence(state)
        
        assert result is not None
        assert result.silence_type == SilenceType.CONCENTRATION
    
    def test_no_silence_normal_speed(self):
        from src.silence_controller import SilenceController
        from dataclasses import dataclass
        
        @dataclass
        class MockState:
            current_speed: float = 1.0
            scene_facts: dict = None
            recent_events: list = None
            
            def __post_init__(self):
                self.scene_facts = self.scene_facts or {}
                self.recent_events = self.recent_events or []
        
        controller = SilenceController()
        state = MockState()
        
        result = controller.should_silence(state)
        
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

---

## 実行手順

1. **ファイル作成**: 上記のファイルを指定のパスに作成
2. **依存関係確認**: `pip install pyyaml pytest`
3. **テスト実行**: `pytest tests/test_v2_1_components.py -v`
4. **既存コードとの統合**: `src/character.py` の修正例を参考に統合

## 注意事項

- 既存のLLM呼び出し処理（vLLM, Ollama等）は `_call_llm` メソッドに実装してください
- `persona/` ディレクトリの構造は既存のものに合わせて調整してください
- 本番環境では `NoveltyGuard.extract_nouns()` にMeCab等の形態素解析を使用することを推奨します
