"""
VLM出力を構造化してDuoSignalsに注入

汎用的なVLM出力パース機能を提供。
Florence-2, Gemma3-VLM, キャプション等に対応。
"""
from datetime import datetime
from typing import Dict, Optional, Any
import re

from src.signals import DuoSignals, SignalEvent, EventType


class VisionToSignals:
    """VLM出力 → DuoSignals.scene_facts 変換"""

    def __init__(self, signals: Optional[DuoSignals] = None):
        """
        Args:
            signals: DuoSignals インスタンス（Noneならシングルトン取得）
        """
        self._signals = signals

    @property
    def signals(self) -> DuoSignals:
        """DuoSignals インスタンスを取得（遅延初期化）"""
        if self._signals is None:
            self._signals = DuoSignals()
        return self._signals

    def parse_florence_output(self, florence_text: str) -> Dict[str, str]:
        """
        Florence-2のOD出力をパース

        例: '<OD>car<loc_52><loc_63><loc_78><loc_89>'
        → {"detected_objects": "car", "primary_object": "car", "position": "center"}

        Args:
            florence_text: Florence-2の生の出力テキスト

        Returns:
            パース結果の辞書
        """
        scene_facts: Dict[str, str] = {}

        # 物体検出結果抽出
        # パターン: <OD>object1<loc_x1><loc_y1><loc_x2><loc_y2>object2...
        objects = re.findall(r'<OD>([^<]+)', florence_text)

        # 追加の物体（loc タグの後に続く）
        additional_objects = re.findall(r'<loc_\d+>([a-zA-Z][^<]*)', florence_text)
        all_objects = objects + [obj.strip() for obj in additional_objects if obj.strip()]

        if all_objects:
            # 重複除去して上位3個
            unique_objects = list(dict.fromkeys(all_objects))[:3]
            scene_facts["detected_objects"] = ", ".join(unique_objects)
            scene_facts["primary_object"] = unique_objects[0]
            scene_facts["object_count"] = str(len(all_objects))

        # 位置情報（簡易版）
        loc_pattern = r'<loc_(\d+)>'
        locs = re.findall(loc_pattern, florence_text)
        if len(locs) >= 4:
            x1, y1, x2, y2 = map(int, locs[:4])
            center_x = (x1 + x2) / 2

            if center_x < 33:
                scene_facts["position"] = "left"
            elif center_x > 66:
                scene_facts["position"] = "right"
            else:
                scene_facts["position"] = "center"

        return scene_facts

    def parse_caption(self, caption_text: str) -> Dict[str, str]:
        """
        キャプション結果をパース

        例: "A car driving on a road with trees"
        → {"scene_type": "outdoor", "activity": "moving", "lighting": "bright"}

        Args:
            caption_text: キャプションテキスト

        Returns:
            パース結果の辞書
        """
        scene_facts: Dict[str, str] = {}

        text_lower = caption_text.lower()

        # シーン判定
        if any(word in text_lower for word in ["indoor", "room", "inside", "building", "house"]):
            scene_facts["scene_type"] = "indoor"
        elif any(word in text_lower for word in ["outdoor", "road", "street", "park", "sky", "tree"]):
            scene_facts["scene_type"] = "outdoor"
        elif any(word in text_lower for word in ["track", "racing", "circuit", "course"]):
            scene_facts["scene_type"] = "racing"
        else:
            scene_facts["scene_type"] = "unknown"

        # 活動判定
        if any(word in text_lower for word in ["driving", "moving", "running", "walking", "going"]):
            scene_facts["activity"] = "moving"
        elif any(word in text_lower for word in ["stopped", "parked", "standing", "waiting", "idle"]):
            scene_facts["activity"] = "stopped"

        # 照明判定
        if any(word in text_lower for word in ["dark", "night", "shadow", "dim"]):
            scene_facts["lighting"] = "dark"
        elif any(word in text_lower for word in ["bright", "sunny", "day", "light"]):
            scene_facts["lighting"] = "bright"
        else:
            scene_facts["lighting"] = "normal"

        # 天候判定
        if any(word in text_lower for word in ["rain", "wet", "water"]):
            scene_facts["weather"] = "rainy"
        elif any(word in text_lower for word in ["snow", "ice", "frozen"]):
            scene_facts["weather"] = "snowy"
        elif any(word in text_lower for word in ["sunny", "clear"]):
            scene_facts["weather"] = "clear"

        # キャプション保存（最大200文字）
        scene_facts["caption"] = caption_text[:200]

        return scene_facts

    def parse_vlm_output(self, vlm_text: str) -> Dict[str, str]:
        """
        Gemma3-VLM等の自然言語出力をパース

        例: "画像には赤い車が道路の右側を走っています"
        → {"color": "red", "lane": "right", "vlm_description": "..."}

        Args:
            vlm_text: VLMの自然言語出力

        Returns:
            パース結果の辞書
        """
        scene_facts: Dict[str, str] = {}

        text_lower = vlm_text.lower()

        # 色検出（英語・日本語）
        color_map = {
            "red": "red", "赤": "red", "赤い": "red",
            "blue": "blue", "青": "blue", "青い": "blue",
            "green": "green", "緑": "green",
            "yellow": "yellow", "黄": "yellow", "黄色": "yellow",
            "white": "white", "白": "white", "白い": "white",
            "black": "black", "黒": "black", "黒い": "black",
            "orange": "orange", "オレンジ": "orange",
            "gray": "gray", "grey": "gray", "灰色": "gray",
        }
        for keyword, color in color_map.items():
            if keyword in text_lower or keyword in vlm_text:
                scene_facts["color"] = color
                break

        # 位置検出（英語・日本語）
        if any(word in text_lower for word in ["right", "右側", "右"]):
            scene_facts["lane"] = "right"
        elif any(word in text_lower for word in ["left", "左側", "左"]):
            scene_facts["lane"] = "left"
        elif any(word in text_lower for word in ["center", "中央", "真ん中"]):
            scene_facts["lane"] = "center"

        # 障害物検出
        obstacle_keywords = [
            "cone", "コーン", "パイロン",
            "barrier", "バリア", "柵",
            "obstacle", "障害物",
            "人", "person", "pedestrian",
        ]
        for obs in obstacle_keywords:
            if obs in text_lower or obs in vlm_text:
                scene_facts["obstacle"] = obs
                break

        # 道路状態
        if any(word in text_lower for word in ["curve", "カーブ", "曲がり"]):
            scene_facts["upcoming"] = "curve"
        elif any(word in text_lower for word in ["straight", "直線", "まっすぐ"]):
            scene_facts["upcoming"] = "straight"
        elif any(word in text_lower for word in ["corner", "コーナー", "角"]):
            scene_facts["upcoming"] = "corner"

        # VLM説明保存（最大200文字）
        scene_facts["vlm_description"] = vlm_text[:200]

        return scene_facts

    def parse_segmentation_result(self, seg_result: Dict[str, Any]) -> Dict[str, str]:
        """
        セグメンテーション結果をパース

        Args:
            seg_result: セグメンテーション結果の辞書

        Returns:
            パース結果の辞書
        """
        scene_facts: Dict[str, str] = {}

        # 道路占有率
        if "road_percentage" in seg_result:
            pct = seg_result["road_percentage"]
            if isinstance(pct, (int, float)):
                scene_facts["road_percentage"] = f"{pct:.0f}%"
            else:
                scene_facts["road_percentage"] = str(pct)

        # ナビゲーションヒント
        if "navigation_hint" in seg_result:
            scene_facts["navigation_hint"] = seg_result["navigation_hint"]

        # 推論時間
        if "inference_time" in seg_result:
            scene_facts["inference_time"] = f"{seg_result['inference_time']:.0f}ms"

        return scene_facts

    def inject_to_signals(
        self,
        vision_output: Dict[str, str],
        source: str = "unknown"
    ) -> None:
        """
        DuoSignals.scene_factsに注入

        Args:
            vision_output: パース済みの視覚情報
            source: "florence", "vlm", "caption", "segmentation" など
        """
        # scene_factsに追加（既存データとマージ）
        vision_output["vision_source"] = source
        vision_output["vision_timestamp"] = datetime.now().isoformat()

        # SignalEvent を使って注入
        self.signals.update(SignalEvent(
            event_type=EventType.VLM,
            data={"facts": vision_output}
        ))

    def process_florence(self, florence_text: str, inject: bool = True) -> Dict[str, str]:
        """
        Florence-2出力を処理してSignalsに注入

        Args:
            florence_text: Florence-2の生出力
            inject: Signalsに注入するか

        Returns:
            パース結果
        """
        result = self.parse_florence_output(florence_text)
        if inject and result:
            self.inject_to_signals(result, source="florence")
        return result

    def process_caption(self, caption_text: str, inject: bool = True) -> Dict[str, str]:
        """
        キャプションを処理してSignalsに注入

        Args:
            caption_text: キャプションテキスト
            inject: Signalsに注入するか

        Returns:
            パース結果
        """
        result = self.parse_caption(caption_text)
        if inject and result:
            self.inject_to_signals(result, source="caption")
        return result

    def process_vlm(self, vlm_text: str, inject: bool = True) -> Dict[str, str]:
        """
        VLM出力を処理してSignalsに注入

        Args:
            vlm_text: VLMの自然言語出力
            inject: Signalsに注入するか

        Returns:
            パース結果
        """
        result = self.parse_vlm_output(vlm_text)
        if inject and result:
            self.inject_to_signals(result, source="vlm")
        return result

    def get_current_scene_facts(self) -> Dict[str, str]:
        """現在のscene_factsを取得"""
        state = self.signals.snapshot()
        return state.scene_facts
