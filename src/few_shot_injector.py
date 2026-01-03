"""
duo-talk v2.1 - FewShotInjector
状況に応じたFew-shotパターンを選択・注入

機能:
- patterns.yaml からパターンを読み込み
- NoveltyGuardの戦略と連携
- SilenceControllerとの連携
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


class FewShotInjector:
    """
    状況に応じたFew-shotパターンを選択・注入

    使用例:
        injector = FewShotInjector()

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

    def __init__(self, patterns_path: str = "persona/few_shots/patterns.yaml"):
        self.patterns_path = config.project_root / patterns_path
        self.patterns: List[FewShotPattern] = []
        self._load_patterns()

    def _load_patterns(self) -> None:
        """パターンファイルを読み込み"""
        if not self.patterns_path.exists():
            print(f"Warning: Few-shot patterns file not found: {self.patterns_path}")
            return

        with open(self.patterns_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        for p in data.get("patterns", []):
            self.patterns.append(FewShotPattern(
                id=p.get("id", ""),
                triggers=p.get("trigger", []),
                description=p.get("description", ""),
                example=p.get("example", ""),
                note=p.get("note")
            ))

    def reload_patterns(self) -> None:
        """パターンを再読み込み（ホットリロード用）"""
        self.patterns.clear()
        self._load_patterns()

    def select_pattern(
        self,
        signals_state: Any,
        loop_strategy: Optional[LoopBreakStrategy] = None,
        event_type: Optional[str] = None
    ) -> Optional[str]:
        """
        現在の状況に最適なパターンを選択

        Args:
            signals_state: DuoSignalsのスナップショット
            loop_strategy: NoveltyGuardが選択した戦略（ループ検知時）
            event_type: 発生したイベントタイプ（success, failure等）

        Returns:
            選択されたパターンのexample文字列、または None
        """
        # 1. NoveltyGuard戦略に対応するパターン
        if loop_strategy and loop_strategy != LoopBreakStrategy.NOOP:
            strategy_pattern = self._get_pattern_for_strategy(loop_strategy)
            if strategy_pattern:
                return strategy_pattern

        # 2. イベントタイプに対応するパターン
        if event_type:
            event_pattern = self._get_pattern_for_event(event_type)
            if event_pattern:
                return event_pattern

        # 3. センサー状態からの自動選択
        auto_pattern = self._auto_select_from_state(signals_state)
        if auto_pattern:
            return auto_pattern

        return None

    def _get_pattern_for_strategy(self, strategy: LoopBreakStrategy) -> Optional[str]:
        """戦略に対応するパターンを取得"""
        strategy_pattern_map = {
            LoopBreakStrategy.FORCE_SPECIFIC_SLOT: "specific_slot_example",
            LoopBreakStrategy.FORCE_CONFLICT_WITHIN: "conflict_within_example",
            LoopBreakStrategy.FORCE_ACTION_NEXT: "action_next_example",
            LoopBreakStrategy.FORCE_PAST_REFERENCE: "past_reference_example",
        }

        pattern_id = strategy_pattern_map.get(strategy)
        return self._get_pattern_by_id(pattern_id)

    def _get_pattern_for_event(self, event_type: str) -> Optional[str]:
        """イベントタイプに対応するパターンを取得"""
        event_pattern_map = {
            "success": "success_credit",
            "failure": "failure_support",
            "collision": "failure_support",
            "sensor_anomaly": "discovery_supplement",
        }

        pattern_id = event_pattern_map.get(event_type)
        return self._get_pattern_by_id(pattern_id)

    def _auto_select_from_state(self, state: Any) -> Optional[str]:
        """状態から自動的にパターンを選択"""
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
            if upcoming in ["difficult_corner", "sharp_turn"]:
                return self._get_pattern_by_id("pre_tension")

        return None

    def _get_pattern_by_id(self, pattern_id: Optional[str]) -> Optional[str]:
        """IDでパターンを取得"""
        if not pattern_id:
            return None

        for p in self.patterns:
            if p.id == pattern_id:
                return p.example
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


# シングルトンインスタンス
_injector: Optional[FewShotInjector] = None


def get_few_shot_injector(patterns_path: str = "persona/few_shots/patterns.yaml") -> FewShotInjector:
    """FewShotInjectorを取得（シングルトン）"""
    global _injector
    if _injector is None:
        _injector = FewShotInjector(patterns_path)
    return _injector


def reset_few_shot_injector() -> None:
    """FewShotInjectorをリセット"""
    global _injector
    _injector = None
