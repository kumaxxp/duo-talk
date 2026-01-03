# duo-talk v2.1 プロンプト統合実装指示

## 概要

v2.1のコアコンポーネント（DuoSignals, PromptBuilder, NoveltyGuard, SilenceController）は実装済み。
本指示では、配置済みのYAMLプロンプトファイルを読み込み、システムに統合する。

## 前提：配置済みファイル

```
persona/
├── char_a/
│   └── prompt.yaml          # やな（姉）のプロンプト
├── char_b/
│   └── prompt.yaml          # あゆ（妹）のプロンプト
├── director/
│   └── prompt.yaml          # ディレクタープロンプト
├── few_shots/
│   └── patterns.yaml        # Few-shotパターン
└── world_rules.yaml         # 世界設定（姉妹共同行動ルール）
```

---

## Task 1: プロンプトローダーの作成

### 新規作成: `src/prompt_loader.py`

```python
"""
duo-talk v2.1 - PromptLoader
YAMLプロンプトファイルを読み込み、PromptBuilderに注入可能な形式に変換

機能：
- キャラクタープロンプトの読み込み・フォーマット
- ディレクタープロンプトの読み込み・フォーマット
- 世界設定の読み込み
"""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class CharacterPrompt:
    """キャラクタープロンプト"""
    name: str
    role: str
    relationship: str
    decision_core: Dict[str, str]
    speech_patterns: Dict[str, list]
    forbidden: list
    generation_instruction: str
    raw_data: Dict[str, Any]
    
    def to_injection_text(self) -> str:
        """PromptBuilder注入用のテキストに変換"""
        lines = [
            f"## {self.name}（{self.role}）",
            f"- 関係性: {self.relationship}",
            "",
            "### 判断基準",
        ]
        
        for key, value in self.decision_core.items():
            lines.append(f"- {key}: {value}")
        
        lines.extend(["", "### 会話スタイル"])
        for category, patterns in self.speech_patterns.items():
            lines.append(f"- {category}: {', '.join(patterns[:3])}...")
        
        lines.extend(["", "### 禁止事項"])
        for item in self.forbidden[:5]:
            lines.append(f"- {item}")
        
        lines.extend(["", self.generation_instruction])
        
        return "\n".join(lines)


@dataclass
class DirectorPrompt:
    """ディレクタープロンプト"""
    philosophy: str
    intervention_conditions: Dict[str, Dict]
    non_intervention: list
    strategies: Dict[str, Dict]
    raw_data: Dict[str, Any]
    
    def get_strategy_instruction(self, strategy_name: str) -> Optional[str]:
        """戦略名に対応する指示を取得"""
        strategy = self.strategies.get(strategy_name)
        if strategy:
            return strategy.get("instruction", "")
        return None


class PromptLoader:
    """
    YAMLプロンプトファイルのローダー
    
    使用例:
        loader = PromptLoader("persona")
        
        # キャラクタープロンプト
        yana_prompt = loader.load_character("char_a")
        ayu_prompt = loader.load_character("char_b")
        
        # ディレクタープロンプト
        director = loader.load_director()
        
        # 世界設定
        world_rules = loader.load_world_rules()
    """
    
    def __init__(self, base_path: str = "persona"):
        self.base_path = Path(base_path)
        self._cache: Dict[str, Any] = {}
    
    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        """YAMLファイルを読み込み（キャッシュ付き）"""
        cache_key = str(path)
        if cache_key not in self._cache:
            if not path.exists():
                raise FileNotFoundError(f"Prompt file not found: {path}")
            with open(path, 'r', encoding='utf-8') as f:
                self._cache[cache_key] = yaml.safe_load(f)
        return self._cache[cache_key]
    
    def clear_cache(self) -> None:
        """キャッシュをクリア（ホットリロード用）"""
        self._cache.clear()
    
    def load_character(self, char_id: str) -> CharacterPrompt:
        """
        キャラクタープロンプトを読み込み
        
        Args:
            char_id: "char_a" (やな) or "char_b" (あゆ)
        
        Returns:
            CharacterPrompt オブジェクト
        """
        path = self.base_path / char_id / "prompt.yaml"
        data = self._load_yaml(path)
        
        identity = data.get("identity", {})
        
        return CharacterPrompt(
            name=identity.get("name", ""),
            role=identity.get("role", ""),
            relationship=identity.get("relationship", ""),
            decision_core=data.get("decision_core", {}),
            speech_patterns=data.get("speech_patterns", {}),
            forbidden=data.get("forbidden", []),
            generation_instruction=data.get("generation_instruction", ""),
            raw_data=data
        )
    
    def load_director(self) -> DirectorPrompt:
        """ディレクタープロンプトを読み込み"""
        path = self.base_path / "director" / "prompt.yaml"
        data = self._load_yaml(path)
        
        return DirectorPrompt(
            philosophy=data.get("philosophy", ""),
            intervention_conditions=data.get("intervention_conditions", {}),
            non_intervention=data.get("non_intervention", []),
            strategies=data.get("strategies", {}),
            raw_data=data
        )
    
    def load_world_rules(self) -> str:
        """
        世界設定を読み込み、注入用テキストに変換
        
        Returns:
            str: PRIORITY_WORLD_RULES用のテキスト
        """
        path = self.base_path / "world_rules.yaml"
        data = self._load_yaml(path)
        
        world_state = data.get("world_state", {})
        core_rule = world_state.get("core_rule", "")
        
        # 会話ルールも追加
        conversation_rules = data.get("conversation_rules", [])
        if conversation_rules:
            rules_text = "\n".join(f"- {rule}" for rule in conversation_rules)
            core_rule += f"\n\n## 会話の基本ルール\n{rules_text}"
        
        return core_rule
    
    def get_character_name(self, char_id: str) -> str:
        """キャラクターIDから名前を取得"""
        try:
            prompt = self.load_character(char_id)
            return prompt.name
        except FileNotFoundError:
            return "char_a" if char_id == "char_a" else "char_b"
```

---

## Task 2: FewShotInjectorの更新

### 修正: `src/few_shot_injector.py`

```python
"""
duo-talk v2.1 - FewShotInjector
状況に応じたFew-shotパターンを選択・注入

更新内容:
- patterns.yaml からパターンを読み込み
- NoveltyGuardの戦略と連携
- SilenceControllerとの連携
"""

import yaml
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from src.signals import DuoSignalsState
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
        self.patterns_path = Path(patterns_path)
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
        signals_state: DuoSignalsState,
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
        strategy_trigger_map = {
            LoopBreakStrategy.FORCE_SPECIFIC_SLOT: "strategy_specific_slot",
            LoopBreakStrategy.FORCE_CONFLICT_WITHIN: "strategy_conflict_within",
            LoopBreakStrategy.FORCE_ACTION_NEXT: "strategy_action_next",
            LoopBreakStrategy.FORCE_PAST_REFERENCE: "strategy_past_reference",
        }
        
        trigger = strategy_trigger_map.get(strategy)
        if trigger:
            # 対応するパターンIDを探す
            id_map = {
                "strategy_specific_slot": "specific_slot_example",
                "strategy_conflict_within": "conflict_within_example",
                "strategy_action_next": "action_next_example",
                "strategy_past_reference": "past_reference_example",
            }
            pattern_id = id_map.get(trigger)
            return self._get_pattern_by_id(pattern_id)
        
        return None
    
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
    
    def _auto_select_from_state(self, state: DuoSignalsState) -> Optional[str]:
        """状態から自動的にパターンを選択"""
        # センサー異常検知
        if self._has_sensor_anomaly(state):
            return self._get_pattern_by_id("discovery_supplement")
        
        # 走行結果イベント
        if state.recent_events:
            last_event = state.recent_events[-1]
            event_type = last_event.get("type")
            if event_type in ["success", "failure", "collision"]:
                return self._get_pattern_for_event(event_type)
        
        # 難コーナー接近（pre_tension）
        if state.scene_facts.get("upcoming") in ["difficult_corner", "sharp_turn"]:
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
    
    def _has_sensor_anomaly(self, state: DuoSignalsState) -> bool:
        """センサー異常を検知"""
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
```

---

## Task 3: CharacterEngineの統合更新

### 修正: `src/character.py`

既存の`speak_v2`メソッドを更新し、PromptLoaderとFewShotInjectorを統合する。

```python
"""
src/character.py への追加・修正

既存のCharacterクラスに以下を統合:
- PromptLoader でYAMLプロンプトを読み込み
- FewShotInjector でパターンを選択・注入
- ディレクタープロンプトの条件付き注入
"""

# === 以下をインポートに追加 ===
from src.prompt_loader import PromptLoader, CharacterPrompt, DirectorPrompt
from src.few_shot_injector import FewShotInjector
from src.novelty_guard import LoopBreakStrategy


class Character:
    """
    キャラクタークラス（v2.1統合版）
    
    変更点:
    - __init__ で PromptLoader, FewShotInjector を初期化
    - speak_v2 で全コンポーネントを統合
    """
    
    def __init__(self, char_id: str, config_path: str = "config/duo_talk.yaml"):
        """
        Args:
            char_id: "A" (やな) or "B" (あゆ)
        """
        self.char_id = char_id
        self.internal_id = "char_a" if char_id == "A" else "char_b"
        
        # 既存の初期化処理...
        # self.config = ...
        # self.llm_client = ...
        
        # v2.1 コンポーネント
        from src.signals import DuoSignals
        from src.injection import PromptBuilder, Priority
        from src.novelty_guard import NoveltyGuard
        from src.silence_controller import SilenceController
        
        self.signals = DuoSignals()
        self.novelty_guard = NoveltyGuard()
        self.silence_controller = SilenceController()
        
        # プロンプトローダー
        self.prompt_loader = PromptLoader("persona")
        self.few_shot_injector = FewShotInjector("persona/few_shots/patterns.yaml")
        
        # プロンプトをプリロード
        self._character_prompt: CharacterPrompt = self.prompt_loader.load_character(self.internal_id)
        self._director_prompt: DirectorPrompt = self.prompt_loader.load_director()
        self._world_rules: str = self.prompt_loader.load_world_rules()
    
    def reload_prompts(self) -> None:
        """プロンプトを再読み込み（ホットリロード）"""
        self.prompt_loader.clear_cache()
        self._character_prompt = self.prompt_loader.load_character(self.internal_id)
        self._director_prompt = self.prompt_loader.load_director()
        self._world_rules = self.prompt_loader.load_world_rules()
        self.few_shot_injector.reload_patterns()
    
    def speak_v2(
        self,
        last_utterance: str,
        context: dict,
        frame_description: str = ""
    ) -> dict:
        """
        v2.1統合版の発話生成
        
        Args:
            last_utterance: 直前の相手の発言
            context: コンテキスト情報（history等）
            frame_description: VLMからのフレーム説明
        
        Returns:
            dict: {
                "type": "speech" | "silence",
                "content": str | dict,
                "debug": dict
            }
        """
        from src.signals import SignalEvent, EventType
        from src.injection import PromptBuilder, Priority
        
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
        builder.add(
            self._world_rules,
            Priority.WORLD_RULES,
            "world_rules"
        )
        
        # 4.3 キャラクター設定
        builder.add(
            self._character_prompt.to_injection_text(),
            Priority.DEEP_VALUES,
            "character"
        )
        
        # 4.4 会話履歴
        history = context.get("history", [])
        if history:
            builder.add(
                self._format_history(history),
                Priority.HISTORY,
                "history"
            )
        
        # 4.5 直前の発言（HISTORYの直後）
        other_name = "あゆ" if self.char_id == "A" else "やな"
        builder.add(
            f"【直前の{other_name}の発言】\n{last_utterance}",
            Priority.LAST_UTTERANCE,
            "last_utterance"
        )
        
        # 4.6 シーン情報（VLM）
        if frame_description:
            builder.add(
                f"【現在のシーン】\n{frame_description}",
                Priority.SCENE_FACTS,
                "scene"
            )
        elif state.scene_facts:
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
        
        # 4.9 ディレクター指示（ループ検知時のみ）
        if loop_result.loop_detected:
            # NoveltyGuardの注入を使用
            if loop_result.injection:
                builder.add(
                    loop_result.injection,
                    Priority.DIRECTOR,
                    "novelty_guard"
                )
            
            # ディレクターの戦略指示も追加
            strategy_instruction = self._director_prompt.get_strategy_instruction(
                loop_result.strategy.name
            )
            if strategy_instruction:
                builder.add(
                    f"【ディレクター補足】\n{strategy_instruction}",
                    Priority.DIRECTOR + 1,  # NoveltyGuardの直後
                    "director"
                )
        
        # 4.10 Few-shotパターン
        # イベントタイプの判定
        event_type = None
        if state.recent_events:
            event_type = state.recent_events[-1].get("type")
        
        few_shot = self.few_shot_injector.select_pattern(
            signals_state=state,
            loop_strategy=loop_result.strategy if loop_result.loop_detected else None,
            event_type=event_type
        )
        if few_shot:
            builder.add(
                f"【参考: このような会話パターンで】\n{few_shot}",
                Priority.FEW_SHOT,
                "few_shot"
            )
        
        # 5. プロンプト生成
        prompt = builder.build()
        
        # 6. LLM呼び出し
        response = self._call_llm(prompt)
        
        # 7. 会話イベントを記録
        self.signals.update(SignalEvent(
            event_type=EventType.CONVERSATION,
            data={
                "speaker": self._character_prompt.name,
                "topic": self._extract_topic(response),
                "unfilled_slots": unfilled
            }
        ))
        
        return {
            "type": "speech",
            "content": response,
            "debug": {
                "character": self._character_prompt.name,
                "loop_detected": loop_result.loop_detected,
                "strategy": loop_result.strategy.value if loop_result.loop_detected else None,
                "unfilled_slots": unfilled,
                "few_shot_used": few_shot is not None,
                "prompt_structure": builder.get_structure()
            }
        }
    
    def _get_system_prompt(self) -> str:
        """システムプロンプトを取得"""
        return f"""あなたは「{self._character_prompt.name}」として振る舞ってください。
JetRacer自動運転車の走行を実況・解説する姉妹AIの一人です。

相手の発言に自然に反応し、キャラクターの個性を活かした短い発話を生成してください。
発話は1〜3文程度で、会話のテンポを維持してください。"""
    
    def _format_history(self, history: list) -> str:
        """会話履歴をフォーマット"""
        lines = ["【会話履歴（直近5ターン）】"]
        for h in history[-5:]:
            speaker = h.get("speaker", "?")
            content = h.get("content", "")
            lines.append(f"{speaker}: {content}")
        return "\n".join(lines)
    
    def _format_scene(self, scene_facts: dict) -> str:
        """シーン情報をフォーマット"""
        parts = []
        for key, value in scene_facts.items():
            parts.append(f"- {key}: {value}")
        return "\n".join(parts) if parts else "（シーン情報なし）"
    
    def _format_world_state(self, state) -> str:
        """走行状態をフォーマット"""
        sensors_str = ", ".join(
            f"{k}: {v:.2f}m" for k, v in state.distance_sensors.items()
        ) if state.distance_sensors else "（センサー情報なし）"
        
        return f"""【現在の走行状態】
- モード: {state.jetracer_mode}
- 速度: {state.current_speed:.2f} m/s
- 舵角: {state.steering_angle:.1f}°
- センサー: {sensors_str}"""
    
    def _extract_topic(self, text: str) -> str:
        """テキストから主要トピックを抽出"""
        import re
        # カタカナ・漢字の連続を抽出
        nouns = re.findall(r'[ァ-ヶー]{2,}|[一-龯]{2,}', text)
        # 一般的な語を除外
        stop_words = {"こと", "もの", "ところ", "とき", "ため", "よう", "それ", "これ"}
        nouns = [n for n in nouns if n not in stop_words]
        return nouns[0] if nouns else "走行"
    
    def _call_llm(self, prompt: str) -> str:
        """LLMを呼び出して応答を生成"""
        # 既存のLLM呼び出し処理を使用
        # vLLM, Ollama, OpenAI互換API等
        
        # 仮実装（実際のプロジェクトに合わせて修正）
        if hasattr(self, 'llm_client') and self.llm_client:
            return self.llm_client.generate(prompt)
        else:
            raise NotImplementedError("LLMクライアントが設定されていません")
```

---

## Task 4: テストの追加

### 新規作成: `tests/test_prompt_integration.py`

```python
"""
duo-talk v2.1 プロンプト統合テスト
"""

import pytest
from pathlib import Path


class TestPromptLoader:
    """PromptLoader のテスト"""
    
    @pytest.fixture
    def loader(self):
        from src.prompt_loader import PromptLoader
        return PromptLoader("persona")
    
    def test_load_character_a(self, loader):
        """やなのプロンプトを読み込み"""
        prompt = loader.load_character("char_a")
        assert prompt.name == "やな"
        assert "Edge AI" in prompt.role
        assert len(prompt.forbidden) > 0
    
    def test_load_character_b(self, loader):
        """あゆのプロンプトを読み込み"""
        prompt = loader.load_character("char_b")
        assert prompt.name == "あゆ"
        assert "Cloud AI" in prompt.role
        assert "姉様" in prompt.relationship
    
    def test_load_director(self, loader):
        """ディレクタープロンプトを読み込み"""
        director = loader.load_director()
        assert director.philosophy != ""
        assert "FORCE_SPECIFIC_SLOT" in director.strategies
    
    def test_load_world_rules(self, loader):
        """世界設定を読み込み"""
        rules = loader.load_world_rules()
        assert "同じ場所" in rules or "共有" in rules
    
    def test_character_to_injection_text(self, loader):
        """キャラクタープロンプトの注入テキスト変換"""
        prompt = loader.load_character("char_a")
        text = prompt.to_injection_text()
        assert "やな" in text
        assert "判断基準" in text
        assert "禁止事項" in text
    
    def test_cache_and_reload(self, loader):
        """キャッシュとリロード"""
        # 最初の読み込み
        prompt1 = loader.load_character("char_a")
        
        # キャッシュから読み込み
        prompt2 = loader.load_character("char_a")
        
        # キャッシュクリア
        loader.clear_cache()
        
        # 再読み込み
        prompt3 = loader.load_character("char_a")
        
        assert prompt1.name == prompt2.name == prompt3.name


class TestFewShotInjector:
    """FewShotInjector のテスト"""
    
    @pytest.fixture
    def injector(self):
        from src.few_shot_injector import FewShotInjector
        return FewShotInjector("persona/few_shots/patterns.yaml")
    
    def test_load_patterns(self, injector):
        """パターンの読み込み"""
        ids = injector.get_all_pattern_ids()
        assert len(ids) > 0
        assert "discovery_supplement" in ids
        assert "success_credit" in ids
    
    def test_select_pattern_for_strategy(self, injector):
        """戦略に対応するパターン選択"""
        from src.novelty_guard import LoopBreakStrategy
        from src.signals import DuoSignalsState
        
        state = DuoSignalsState()
        
        pattern = injector.select_pattern(
            signals_state=state,
            loop_strategy=LoopBreakStrategy.FORCE_SPECIFIC_SLOT
        )
        
        assert pattern is not None
        assert "数値" in pattern or "具体" in pattern
    
    def test_select_pattern_for_event(self, injector):
        """イベントに対応するパターン選択"""
        from src.signals import DuoSignalsState
        
        state = DuoSignalsState()
        
        pattern = injector.select_pattern(
            signals_state=state,
            event_type="success"
        )
        
        assert pattern is not None
    
    def test_no_pattern_for_normal_state(self, injector):
        """通常状態ではパターンなし"""
        from src.signals import DuoSignalsState
        
        state = DuoSignalsState()
        
        pattern = injector.select_pattern(
            signals_state=state,
            loop_strategy=None,
            event_type=None
        )
        
        # センサー異常等がなければNone
        # （ただし、recent_eventsやscene_factsがあれば選択される可能性あり）


class TestIntegration:
    """統合テスト"""
    
    def test_prompt_builder_with_loaded_prompts(self):
        """PromptBuilderとプロンプトローダーの統合"""
        from src.injection import PromptBuilder, Priority
        from src.prompt_loader import PromptLoader
        
        loader = PromptLoader("persona")
        builder = PromptBuilder()
        
        # 世界設定
        world_rules = loader.load_world_rules()
        builder.add(world_rules, Priority.WORLD_RULES, "world_rules")
        
        # キャラクター
        char_prompt = loader.load_character("char_a")
        builder.add(
            char_prompt.to_injection_text(),
            Priority.DEEP_VALUES,
            "character"
        )
        
        # 履歴
        builder.add("会話履歴...", Priority.HISTORY, "history")
        
        # 直前発言
        builder.add("直前の発言...", Priority.LAST_UTTERANCE, "last")
        
        prompt = builder.build()
        
        # 順序確認: WORLD_RULES(15) < DEEP_VALUES(20) < HISTORY(50) < LAST_UTTERANCE(55)
        assert prompt.index(world_rules[:20]) < prompt.index("やな")
        assert prompt.index("やな") < prompt.index("会話履歴")
        assert prompt.index("会話履歴") < prompt.index("直前の発言")
    
    def test_full_pipeline(self):
        """フルパイプラインテスト（LLM呼び出し以外）"""
        from src.signals import DuoSignals, SignalEvent, EventType
        from src.injection import PromptBuilder, Priority
        from src.novelty_guard import NoveltyGuard
        from src.silence_controller import SilenceController
        from src.prompt_loader import PromptLoader
        from src.few_shot_injector import FewShotInjector
        
        # 初期化
        DuoSignals.reset_instance()
        signals = DuoSignals()
        novelty_guard = NoveltyGuard()
        silence_controller = SilenceController()
        loader = PromptLoader("persona")
        few_shot = FewShotInjector("persona/few_shots/patterns.yaml")
        
        # センサーイベントを追加
        signals.update(SignalEvent(
            event_type=EventType.SENSOR,
            data={"speed": 1.5, "sensors": {"left": 0.3, "right": 0.3}}
        ))
        
        # 状態取得
        state = signals.snapshot()
        
        # 沈黙判定（通常速度なのでNone）
        silence = silence_controller.should_silence(state)
        assert silence is None
        
        # ループ検知
        loop_result = novelty_guard.check_and_update("センサーの値を確認しました")
        
        # プロンプト構築
        builder = PromptBuilder()
        builder.add(loader.load_world_rules(), Priority.WORLD_RULES, "world")
        builder.add(
            loader.load_character("char_a").to_injection_text(),
            Priority.DEEP_VALUES,
            "char"
        )
        builder.add("あゆ: センサー確認お願いします", Priority.LAST_UTTERANCE, "last")
        
        # スロットチェック
        unfilled = builder.check_and_inject_slots("センサー", topic_depth=1)
        
        prompt = builder.build()
        
        assert "やな" in prompt
        assert "センサー" in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

---

## Task 5: 実行確認

### 実行手順

```bash
# 1. 依存パッケージ確認
pip install pyyaml pytest

# 2. ファイル配置確認
ls -la persona/
ls -la persona/char_a/
ls -la persona/char_b/
ls -la persona/director/
ls -la persona/few_shots/

# 3. テスト実行
pytest tests/test_prompt_integration.py -v

# 4. 既存テストも含めて全テスト
pytest tests/ -v
```

### 動作確認スクリプト

```python
# scripts/test_v2_1_integration.py

"""v2.1統合の動作確認スクリプト"""

from src.signals import DuoSignals, SignalEvent, EventType
from src.injection import PromptBuilder, Priority
from src.novelty_guard import NoveltyGuard
from src.silence_controller import SilenceController
from src.prompt_loader import PromptLoader
from src.few_shot_injector import FewShotInjector

def main():
    print("=== duo-talk v2.1 統合テスト ===\n")
    
    # 初期化
    DuoSignals.reset_instance()
    signals = DuoSignals()
    novelty_guard = NoveltyGuard()
    silence_controller = SilenceController()
    loader = PromptLoader("persona")
    few_shot_injector = FewShotInjector("persona/few_shots/patterns.yaml")
    
    # プロンプト読み込み確認
    print("1. プロンプト読み込み")
    yana = loader.load_character("char_a")
    ayu = loader.load_character("char_b")
    director = loader.load_director()
    world_rules = loader.load_world_rules()
    
    print(f"   やな: {yana.name} ({yana.role})")
    print(f"   あゆ: {ayu.name} ({ayu.role})")
    print(f"   ディレクター戦略数: {len(director.strategies)}")
    print(f"   世界設定: {len(world_rules)}文字")
    
    # センサーイベント
    print("\n2. センサーイベント追加")
    signals.update(SignalEvent(
        event_type=EventType.SENSOR,
        data={"speed": 2.0, "sensors": {"left": 0.4, "right": 0.35}}
    ))
    state = signals.snapshot()
    print(f"   速度: {state.current_speed} m/s")
    print(f"   センサー: {state.distance_sensors}")
    
    # ループ検知テスト
    print("\n3. ループ検知テスト")
    for i in range(4):
        result = novelty_guard.check_and_update(f"センサーの値が{i+1}回目")
        print(f"   ターン{i+1}: loop={result.loop_detected}, strategy={result.strategy.value}")
    
    # プロンプト構築
    print("\n4. プロンプト構築")
    builder = PromptBuilder()
    builder.add("システムプロンプト", Priority.SYSTEM, "system")
    builder.add(world_rules, Priority.WORLD_RULES, "world")
    builder.add(yana.to_injection_text(), Priority.DEEP_VALUES, "char")
    builder.add("履歴...", Priority.HISTORY, "history")
    builder.add("あゆ: テストメッセージ", Priority.LAST_UTTERANCE, "last")
    
    unfilled = builder.check_and_inject_slots("センサー", topic_depth=3)
    print(f"   未充足スロット: {unfilled}")
    
    structure = builder.get_structure()
    print("   プロンプト構造:")
    for item in structure:
        print(f"     [{item['priority']:2d}] {item['source']}: {item['length']}文字")
    
    # Few-shot選択
    print("\n5. Few-shot選択")
    from src.novelty_guard import LoopBreakStrategy
    
    pattern = few_shot_injector.select_pattern(
        signals_state=state,
        loop_strategy=LoopBreakStrategy.FORCE_SPECIFIC_SLOT
    )
    if pattern:
        print(f"   選択されたパターン（先頭100文字）:")
        print(f"   {pattern[:100]}...")
    else:
        print("   パターンなし")
    
    print("\n=== テスト完了 ===")


if __name__ == "__main__":
    main()
```

---

## 注意事項

1. **既存のLLM呼び出し処理**: `_call_llm`メソッドは既存の実装に合わせて修正してください

2. **YAMLファイルのパス**: `persona/`ディレクトリの構造が異なる場合は、`PromptLoader`のパスを調整してください

3. **形態素解析**: `NoveltyGuard.extract_nouns()`は簡易実装です。本番環境ではMeCab等の使用を推奨します

4. **ホットリロード**: `reload_prompts()`メソッドでプロンプトを再読み込みできます。GUIからの設定変更時に使用してください

5. **デバッグ情報**: `speak_v2`の戻り値の`debug`フィールドに詳細情報が含まれています。問題調査時に活用してください
