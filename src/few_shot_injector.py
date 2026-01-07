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
