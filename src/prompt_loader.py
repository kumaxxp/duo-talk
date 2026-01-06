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
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from src.config import config


@dataclass
class CharacterPrompt:
    """キャラクタープロンプト"""
    name: str
    role: str
    relationship: str
    decision_core: Dict[str, str]
    speech_patterns: Dict[str, List[str]]
    forbidden: List[str]
    generation_instruction: str
    raw_data: Dict[str, Any] = field(default_factory=dict)

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
            if patterns:
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
    intervention_conditions: Dict[str, Dict[str, str]]
    non_intervention: List[str]
    strategies: Dict[str, Dict[str, str]]
    raw_data: Dict[str, Any] = field(default_factory=dict)

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
        self.base_path = config.project_root / base_path
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

    def load_character(self, char_id: str, jetracer_mode: bool = False) -> CharacterPrompt:
        """
        キャラクタープロンプトを読み込み

        Args:
            char_id: "char_a" (やな) or "char_b" (あゆ)
            jetracer_mode: True for JetRacer mode, False for general

        Returns:
            CharacterPrompt オブジェクト
        """
        # モードに応じたファイル名
        if jetracer_mode:
            filename = "prompt_jetracer.yaml"
        else:
            filename = "prompt_general.yaml"

        path = self.base_path / char_id / filename

        # フォールバック: モード別ファイルがなければ prompt.yaml を使用
        if not path.exists():
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

    def load_world_rules(self, jetracer_mode: bool = False) -> str:
        """
        世界設定を読み込み、注入用テキストに変換

        Args:
            jetracer_mode: True for JetRacer mode, False for general

        Returns:
            str: PRIORITY_WORLD_RULES用のテキスト
        """
        # モードに応じたファイル名
        if jetracer_mode:
            filename = "world_rules_jetracer.yaml"
        else:
            filename = "world_rules_general.yaml"

        path = self.base_path / filename

        # フォールバック: モード別ファイルがなければ world_rules.yaml を使用
        if not path.exists():
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
            return "やな" if char_id == "char_a" else "あゆ"


# シングルトンインスタンス
_loader: Optional[PromptLoader] = None


def get_prompt_loader(base_path: str = "persona") -> PromptLoader:
    """PromptLoaderを取得（シングルトン）"""
    global _loader
    if _loader is None:
        _loader = PromptLoader(base_path)
    return _loader


def reset_prompt_loader() -> None:
    """PromptLoaderをリセット"""
    global _loader
    _loader = None
