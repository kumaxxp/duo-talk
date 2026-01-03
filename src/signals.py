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
