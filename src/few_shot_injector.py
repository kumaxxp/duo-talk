"""
duo-talk v2.2 - FewShotInjector
状況に応じたFew-shotパターンを選択・注入

機能:
- patterns.yaml からパターンを読み込み
- NoveltyGuardの戦略と連携
- SilenceControllerとの連携
- JetRacer/一般会話モード対応

v2.2変更点:
- NoveltyGuard新戦略（FORCE_WHY, FORCE_EXPAND）対応
- トピック深度に応じたパターン選択
- 具体性不足時のパターン選択強化
"""

import yaml
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from src.config import config
from src.novelty_guard import LoopBreakStrategy


@dataclass
class FewShotPattern:
    """Few-shotパターン"""
    id: str
    triggers: List[str]
    description: str
    example: str
    note: Optional[str] = None
    mode: Optional[str] = None  # "jetracer" or "general"


class FewShotInjector:
    """
    状況に応じたFew-shotパターンを選択・注入

    使用例:
        injector = FewShotInjector(mode="general")

        # 状況に応じたパターンを取得
        pattern = injector.select_pattern(
            signals_state=state,
            loop_strategy=LoopBreakStrategy.FORCE_SPECIFIC_SLOT
        )

        if pattern:
            builder.add(
                f"【参考パターン】\n{pattern}",
                Priority.FEW_SHOT,
                "few_shot"
            )
    """

    # モード別パターンファイル
    MODE_PATTERNS_MAP = {
        "jetracer": "persona/few_shots/patterns.yaml",
        "general": "persona/few_shots/patterns_general.yaml",
    }

    # 戦略→パターンIDマッピング（モード共通）
    STRATEGY_PATTERN_MAP = {
        LoopBreakStrategy.FORCE_SPECIFIC_SLOT: "specific_slot_example",
        LoopBreakStrategy.FORCE_CONFLICT_WITHIN: "conflict_within_example",
        LoopBreakStrategy.FORCE_ACTION_NEXT: "action_next_example",
        LoopBreakStrategy.FORCE_PAST_REFERENCE: "past_reference_example",
        LoopBreakStrategy.FORCE_WHY: "depth_why",
        LoopBreakStrategy.FORCE_EXPAND: "depth_expand",
    }

    # イベント→パターンIDマッピング
    EVENT_PATTERN_MAP = {
        "success": "success_credit",
        "failure": "failure_support",
        "collision": "failure_support",
        "sensor_anomaly": "discovery_supplement",
        "topic_depth_1": "depth_why",
        "topic_depth_2": "depth_expand",
        "topic_depth_3": "depth_personal",
    }

    # Vision系パターンIDマッピング（Phase 0C追加）
    VISION_PATTERN_MAP = {
        "obstacle": "vision_obstacle_warning",       # 障害物検出（最優先）
        "multiple_objects": "vision_multiple_objects",  # 複数物体
        "lane": "vision_lane",                       # 車線位置
        "environment": "vision_environment",         # 環境・照明
        "discovery": "vision_discovery",             # 基本的な物体検出
    }

    def __init__(
        self,
        patterns_path: Optional[str] = None,
        mode: str = "jetracer"
    ):
        """
        Args:
            patterns_path: パターンファイルパス（指定時はmodeを無視）
            mode: "jetracer" or "general"
        """
        self.mode = mode

        # パターンファイルパスの決定
        if patterns_path:
            self.patterns_path = config.project_root / patterns_path
        else:
            default_path = self.MODE_PATTERNS_MAP.get(mode, self.MODE_PATTERNS_MAP["jetracer"])
            self.patterns_path = config.project_root / default_path

        self.patterns: List[FewShotPattern] = []
        self._load_patterns()

    def _load_patterns(self) -> None:
        """パターンファイルを読み込み"""
        if not self.patterns_path.exists():
            print(f"Warning: Few-shot patterns file not found: {self.patterns_path}")
            return

        try:
            with open(self.patterns_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            for p in data.get("patterns", []):
                self.patterns.append(FewShotPattern(
                    id=p.get("id", ""),
                    triggers=p.get("trigger", []),
                    description=p.get("description", ""),
                    example=p.get("example", ""),
                    note=p.get("note"),
                    mode=p.get("mode", self.mode)
                ))
            
            print(f"[FewShotInjector] Loaded {len(self.patterns)} patterns for mode '{self.mode}'")
        except Exception as e:
            print(f"Warning: Failed to load patterns: {e}")

    def reload_patterns(self) -> None:
        """パターンを再読み込み（ホットリロード用）"""
        self.patterns.clear()
        self._load_patterns()

    def set_mode(self, mode: str) -> None:
        """
        モードを切り替えてパターンを再読み込み

        Args:
            mode: "jetracer" or "general"
        """
        if mode not in self.MODE_PATTERNS_MAP:
            print(f"Warning: Unknown mode '{mode}', defaulting to 'jetracer'")
            mode = "jetracer"

        if self.mode != mode:
            self.mode = mode
            self.patterns_path = config.project_root / self.MODE_PATTERNS_MAP[mode]
            self.reload_patterns()

    def select_pattern(
        self,
        signals_state: Any,
        loop_strategy: Optional[LoopBreakStrategy] = None,
        event_type: Optional[str] = None,
        topic_depth: Optional[int] = None,
        lacks_specificity: bool = False,
    ) -> Optional[str]:
        """
        現在の状況に最適なパターンを選択

        Args:
            signals_state: DuoSignalsのスナップショット
            loop_strategy: NoveltyGuardが選択した戦略（ループ検知時）
            event_type: 発生したイベントタイプ（success, failure等）
            topic_depth: トピック深度（NoveltyGuardから）
            lacks_specificity: 具体性不足フラグ（NoveltyGuardから）

        Returns:
            選択されたパターンのexample文字列、または None
        """
        # 0. Vision情報の優先チェック（Phase 0C追加）
        # 障害物検出は最優先で処理
        if signals_state and hasattr(signals_state, 'scene_facts') and signals_state.scene_facts:
            scene_facts = signals_state.scene_facts
            # 鮮度チェック（5秒以内）
            is_fresh = True
            if hasattr(signals_state, 'is_stale'):
                is_fresh = not signals_state.is_stale(max_age_seconds=5.0)
            elif hasattr(signals_state, 'scene_timestamp') and signals_state.scene_timestamp:
                from datetime import datetime
                age = (datetime.now() - signals_state.scene_timestamp).total_seconds()
                is_fresh = age <= 5.0

            if is_fresh:
                vision_pattern = self._select_vision_pattern(scene_facts)
                if vision_pattern:
                    return vision_pattern

        # 1. 具体性不足の場合は具体化パターンを優先
        if lacks_specificity:
            pattern = self._get_pattern_for_strategy(LoopBreakStrategy.FORCE_SPECIFIC_SLOT)
            if pattern:
                return pattern

        # 2. NoveltyGuard戦略に対応するパターン
        if loop_strategy and loop_strategy != LoopBreakStrategy.NOOP:
            strategy_pattern = self._get_pattern_for_strategy(loop_strategy)
            if strategy_pattern:
                return strategy_pattern

        # 3. トピック深度に応じたパターン
        if topic_depth is not None and topic_depth > 0:
            depth_pattern = self._get_pattern_for_depth(topic_depth)
            if depth_pattern:
                return depth_pattern

        # 4. イベントタイプに対応するパターン
        if event_type:
            event_pattern = self._get_pattern_for_event(event_type)
            if event_pattern:
                return event_pattern

        # 5. センサー状態からの自動選択
        auto_pattern = self._auto_select_from_state(signals_state)
        if auto_pattern:
            return auto_pattern

        return None

    def _get_pattern_for_strategy(self, strategy: LoopBreakStrategy) -> Optional[str]:
        """戦略に対応するパターンを取得"""
        pattern_id = self.STRATEGY_PATTERN_MAP.get(strategy)
        return self._get_pattern_by_id(pattern_id)

    def _get_pattern_for_event(self, event_type: str) -> Optional[str]:
        """イベントタイプに対応するパターンを取得"""
        pattern_id = self.EVENT_PATTERN_MAP.get(event_type)
        return self._get_pattern_by_id(pattern_id)

    def _get_pattern_for_depth(self, depth: int) -> Optional[str]:
        """トピック深度に応じたパターンを取得"""
        depth_pattern_map = {
            1: "depth_why",
            2: "depth_expand",
            3: "depth_personal",
        }
        pattern_id = depth_pattern_map.get(min(depth, 3))
        return self._get_pattern_by_id(pattern_id)

    def _auto_select_from_state(self, state: Any) -> Optional[str]:
        """状態から自動的にパターンを選択"""
        if state is None:
            return None
            
        # センサー異常検知
        if self._has_sensor_anomaly(state):
            return self._get_pattern_by_id("discovery_supplement")

        # 走行結果イベント
        if hasattr(state, 'recent_events') and state.recent_events:
            last_event = state.recent_events[-1]
            if isinstance(last_event, dict):
                event_type = last_event.get("type")
                if event_type in ["success", "failure", "collision"]:
                    return self._get_pattern_for_event(event_type)

        # 難コーナー接近（pre_tension）
        if hasattr(state, 'scene_facts') and state.scene_facts:
            upcoming = state.scene_facts.get("upcoming")
            if upcoming in ["difficult_corner", "sharp_turn", "curve"]:
                return self._get_pattern_by_id("pre_tension")

        # トピック深度
        if hasattr(state, 'topic_depth') and state.topic_depth > 0:
            return self._get_pattern_for_depth(state.topic_depth)

        return None

    def _get_pattern_by_id(self, pattern_id: Optional[str]) -> Optional[str]:
        """IDでパターンを取得"""
        if not pattern_id:
            return None

        for p in self.patterns:
            if p.id == pattern_id:
                return p.example
        
        # パターンが見つからない場合、フォールバック
        # print(f"[FewShotInjector] Pattern '{pattern_id}' not found")
        return None

    def _has_sensor_anomaly(self, state: Any) -> bool:
        """センサー異常を検知"""
        if not hasattr(state, 'distance_sensors'):
            return False

        sensors = state.distance_sensors
        if not sensors or len(sensors) < 2:
            return False

        values = list(sensors.values())
        avg = sum(values) / len(values)

        if avg == 0:
            return False

        for v in values:
            if abs(v - avg) / avg > 0.3:  # 30%以上の乖離
                return True
        return False

    def _select_vision_pattern(self, scene_facts: Dict[str, Any]) -> Optional[str]:
        """
        scene_factsの内容に基づいて最適なvisionパターンを選択

        優先順位:
        1. obstacle検出 → vision_obstacle_warning（最優先）
        2. 複数物体検出 → vision_multiple_objects
        3. lane/position検出 → vision_lane
        4. lighting/scene_type検出 → vision_environment
        5. その他物体検出 → vision_discovery

        Args:
            scene_facts: VisionToSignalsで生成された辞書

        Returns:
            選択されたパターンのexample文字列、または None
        """
        if not scene_facts:
            return None

        # 1. 障害物検出（最優先）
        if "obstacle" in scene_facts:
            pattern_id = self.VISION_PATTERN_MAP.get("obstacle")
            return self._get_pattern_by_id(pattern_id)

        # 2. 複数物体検出
        if "detected_objects" in scene_facts:
            objects = scene_facts["detected_objects"]
            if isinstance(objects, str) and "," in objects:  # 複数ある
                pattern_id = self.VISION_PATTERN_MAP.get("multiple_objects")
                return self._get_pattern_by_id(pattern_id)

        # 3. 車線位置
        if "lane" in scene_facts or ("position" in scene_facts and scene_facts.get("position") in ["left", "right"]):
            pattern_id = self.VISION_PATTERN_MAP.get("lane")
            return self._get_pattern_by_id(pattern_id)

        # 4. 環境・照明
        if "lighting" in scene_facts or "scene_type" in scene_facts:
            pattern_id = self.VISION_PATTERN_MAP.get("environment")
            return self._get_pattern_by_id(pattern_id)

        # 5. 基本的な物体検出
        if "primary_object" in scene_facts or "detected_objects" in scene_facts:
            pattern_id = self.VISION_PATTERN_MAP.get("discovery")
            return self._get_pattern_by_id(pattern_id)

        return None

    def get_all_pattern_ids(self) -> List[str]:
        """全パターンIDを取得（デバッグ用）"""
        return [p.id for p in self.patterns]

    def get_pattern_info(self, pattern_id: str) -> Optional[Dict[str, Any]]:
        """パターンの詳細情報を取得（デバッグ用）"""
        for p in self.patterns:
            if p.id == pattern_id:
                return {
                    "id": p.id,
                    "triggers": p.triggers,
                    "description": p.description,
                    "note": p.note
                }
        return None

    def get_stats(self) -> Dict[str, Any]:
        """統計情報を取得"""
        return {
            "mode": self.mode,
            "patterns_count": len(self.patterns),
            "pattern_ids": self.get_all_pattern_ids(),
        }


# モード別シングルトンインスタンス
_injectors: Dict[str, FewShotInjector] = {}


def get_few_shot_injector(
    patterns_path: Optional[str] = None,
    mode: str = "jetracer"
) -> FewShotInjector:
    """
    FewShotInjectorを取得（モード別シングルトン）

    Args:
        patterns_path: パターンファイルパス（指定時はmodeを無視）
        mode: "jetracer" or "general"

    Returns:
        FewShotInjector インスタンス
    """
    global _injectors

    # パターンパス指定時は専用キーを使用
    cache_key = patterns_path if patterns_path else mode

    if cache_key not in _injectors:
        _injectors[cache_key] = FewShotInjector(patterns_path=patterns_path, mode=mode)

    return _injectors[cache_key]


def reset_few_shot_injector(mode: Optional[str] = None) -> None:
    """
    FewShotInjectorをリセット

    Args:
        mode: リセットするモード（Noneなら全モード）
    """
    global _injectors
    if mode is None:
        _injectors.clear()
    elif mode in _injectors:
        del _injectors[mode]
