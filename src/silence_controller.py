"""
duo-talk v2.1 - SilenceController
沈黙をLLM生成ではなくUI層で制御

設計方針：
- 沈黙はLLMに「...」を生成させない
- action="SILENCE" を返してUI層で演出
- 難コーナー、高速区間、走行直後に適用
"""

from enum import Enum
from typing import Optional, Any, List, Dict
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

    def to_dict(self) -> Dict[str, Any]:
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

    def get_short_utterances(self, silence_type: SilenceType, character: str) -> List[str]:
        """
        沈黙中に許可される短い発話を取得

        Args:
            silence_type: 沈黙タイプ
            character: キャラクター名 ("yana" or "ayu")

        Returns:
            list: 許可される短い発話のリスト
        """
        utterances: Dict[SilenceType, Dict[str, List[str]]] = {
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
