"""
Vision実況リアルタイムループ

JetRacer → Florence-2 → DuoSignals → キャラクター応答のフルパイプライン。
Phase 0Cの最終統合モジュール。

使用例:
    loop = VisionCommentaryLoop(jetracer_url="http://localhost:5000")
    loop.run()  # Ctrl+Cで停止
"""
import time
from datetime import datetime
from typing import Optional, Callable, Dict, Any, List, Tuple
from dataclasses import dataclass, field
import logging

from PIL import Image

from src.jetracer_client import JetRacerClient
from src.florence2_detector import Florence2Detector
from src.vision_to_signals import VisionToSignals
from src.character import Character
from src.signals import DuoSignals, SignalEvent, EventType

logger = logging.getLogger(__name__)


@dataclass
class CommentaryResult:
    """実況結果"""
    yana_comment: str
    ayu_comment: str
    vision_data: Dict[str, Any]
    timing: Dict[str, float]
    timestamp: str
    cycle_number: int
    success: bool = True
    error: Optional[str] = None


@dataclass
class LoopStats:
    """ループ統計"""
    total_cycles: int = 0
    successful_cycles: int = 0
    failed_cycles: int = 0
    total_detection_time: float = 0.0
    total_generation_time: float = 0.0
    total_cycle_time: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_cycles == 0:
            return 0.0
        return self.successful_cycles / self.total_cycles * 100

    @property
    def avg_detection_time(self) -> float:
        if self.successful_cycles == 0:
            return 0.0
        return self.total_detection_time / self.successful_cycles

    @property
    def avg_generation_time(self) -> float:
        if self.successful_cycles == 0:
            return 0.0
        return self.total_generation_time / self.successful_cycles

    @property
    def avg_cycle_time(self) -> float:
        if self.successful_cycles == 0:
            return 0.0
        return self.total_cycle_time / self.successful_cycles


class VisionCommentaryLoop:
    """リアルタイムVision実況システム"""

    def __init__(
        self,
        jetracer_url: str = "http://localhost:5000",
        interval_sec: float = 5.0,
        callback: Optional[Callable[[CommentaryResult], None]] = None,
        load_florence: bool = True
    ):
        """
        Args:
            jetracer_url: JetRacer-Agent APIのURL
            interval_sec: 実況間隔（秒）
            callback: 実況テキスト生成時のコールバック関数
            load_florence: 初期化時にFlorence-2をロードするか
        """
        self.jetracer_url = jetracer_url
        self.interval_sec = interval_sec
        self.callback = callback

        # JetRacerクライアント
        self.jetracer = JetRacerClient(jetracer_url)

        # Florence-2検出器（遅延ロード可能）
        self.detector: Optional[Florence2Detector] = None
        if load_florence:
            self._load_florence()

        # Vision→Signals変換器
        self.converter = VisionToSignals()

        # シングルトンをリセットしてクリーンな状態から
        DuoSignals.reset_instance()
        self.signals = DuoSignals()

        # キャラクター初期化
        self.char_yana = Character('A', jetracer_mode=True)
        self.char_ayu = Character('B', jetracer_mode=True)

        # ループ制御
        self.running = False
        self.stats = LoopStats()

        # 会話履歴（ターン間で保持）
        self.conversation_history: List[Tuple[str, str]] = []
        self.max_history = 10

    def _load_florence(self) -> bool:
        """Florence-2をロード"""
        try:
            print("Loading Florence-2 detector...")
            self.detector = Florence2Detector()
            self.detector.load()
            print(f"Florence-2 loaded (backend: {self.detector._active_backend})")
            return True
        except Exception as e:
            logger.error(f"Failed to load Florence-2: {e}")
            print(f"Failed to load Florence-2: {e}")
            return False

    def check_connection(self) -> bool:
        """JetRacer接続確認"""
        print("Checking JetRacer connection...")
        if self.jetracer.health_check():
            print("JetRacer connected")
            return True
        else:
            print("JetRacer not reachable")
            return False

    def process_single_frame(self) -> CommentaryResult:
        """
        1フレーム分の処理

        Returns:
            CommentaryResult
        """
        timing: Dict[str, float] = {}
        self.stats.total_cycles += 1
        cycle_num = self.stats.total_cycles

        # 1. 画像取得
        start_time = time.time()
        image = self.jetracer.get_camera_image_pil()
        timing["image_fetch"] = time.time() - start_time

        if image is None:
            self.stats.failed_cycles += 1
            return CommentaryResult(
                yana_comment="",
                ayu_comment="",
                vision_data={},
                timing=timing,
                timestamp=datetime.now().isoformat(),
                cycle_number=cycle_num,
                success=False,
                error="Failed to get camera image"
            )

        # 2. Florence-2検出
        start_time = time.time()
        try:
            if self.detector is None or not self.detector._loaded:
                self._load_florence()

            if self.detector and self.detector._loaded:
                detection_result = self.detector.detect(image)
                od_output = detection_result.raw_output.get("OD", "")
            else:
                od_output = ""
            timing["florence_detection"] = time.time() - start_time
        except Exception as e:
            logger.warning(f"Florence-2 detection failed: {e}")
            timing["florence_detection"] = time.time() - start_time
            od_output = ""

        # 3. パース & Signals注入
        start_time = time.time()
        if od_output:
            vision_data = self.converter.parse_florence_output(od_output)
        else:
            vision_data = {"detected_objects": "unknown", "primary_object": "unknown"}

        self.converter.inject_to_signals(vision_data, source="jetracer_live")
        timing["parse_inject"] = time.time() - start_time

        # 4. センサーデータ取得 & Signals更新
        start_time = time.time()
        sensor_data = self.jetracer.get_sensor_data_simple()
        if sensor_data:
            self.signals.update(SignalEvent(
                event_type=EventType.SENSOR,
                data={"sensors": sensor_data}
            ))

        vehicle_state = self.jetracer.get_vehicle_state_simple()
        if vehicle_state:
            self.signals.update(SignalEvent(
                event_type=EventType.SENSOR,
                data={
                    "speed": vehicle_state.get("speed", 0.0),
                    "steering": vehicle_state.get("steering", 0.0)
                }
            ))
        timing["sensor_fetch"] = time.time() - start_time

        # 5. フレーム説明文を生成
        frame_description = self._build_frame_description(vision_data, sensor_data, vehicle_state)

        # 6. やな（発見役）の実況生成
        start_time = time.time()
        try:
            yana_comment = self.char_yana.speak_unified(
                frame_description=frame_description,
                conversation_history=self.conversation_history,
            )
        except Exception as e:
            logger.warning(f"Yana generation failed: {e}")
            yana_comment = "んー、ちょっとわからない..."
        timing["yana_generation"] = time.time() - start_time

        # 履歴に追加
        self.conversation_history.append(("やな", yana_comment))

        # 7. あゆ（解説役）の実況生成
        start_time = time.time()
        try:
            ayu_comment = self.char_ayu.speak_unified(
                frame_description=frame_description,
                conversation_history=self.conversation_history,
            )
        except Exception as e:
            logger.warning(f"Ayu generation failed: {e}")
            ayu_comment = "データ取得中です..."
        timing["ayu_generation"] = time.time() - start_time

        # 履歴に追加
        self.conversation_history.append(("あゆ", ayu_comment))

        # 履歴を制限
        if len(self.conversation_history) > self.max_history:
            self.conversation_history = self.conversation_history[-self.max_history:]

        # 統計更新
        self.stats.successful_cycles += 1
        self.stats.total_detection_time += timing.get("florence_detection", 0)
        self.stats.total_generation_time += timing.get("yana_generation", 0) + timing.get("ayu_generation", 0)
        self.stats.total_cycle_time += sum(timing.values())

        return CommentaryResult(
            yana_comment=yana_comment,
            ayu_comment=ayu_comment,
            vision_data=vision_data,
            timing=timing,
            timestamp=datetime.now().isoformat(),
            cycle_number=cycle_num,
            success=True
        )

    def _build_frame_description(
        self,
        vision_data: Dict[str, Any],
        sensor_data: Optional[Dict[str, float]],
        vehicle_state: Optional[Dict[str, Any]]
    ) -> str:
        """フレーム説明文を構築"""
        parts = []

        # Vision情報
        if vision_data.get("detected_objects"):
            parts.append(f"視界に{vision_data['detected_objects']}が見える")

        if vision_data.get("obstacle"):
            parts.append(f"障害物（{vision_data['obstacle']}）を検出")

        if vision_data.get("position"):
            pos_map = {"left": "左側", "right": "右側", "center": "正面"}
            parts.append(f"位置は{pos_map.get(vision_data['position'], vision_data['position'])}")

        # センサー情報
        if sensor_data:
            front = sensor_data.get("distance_front", 0)
            if front > 0:
                if front < 0.5:
                    parts.append(f"前方{front:.1f}mに接近物あり")
                elif front < 1.0:
                    parts.append(f"前方{front:.1f}mに物体")

        # 車両状態
        if vehicle_state:
            speed = vehicle_state.get("speed", 0)
            if speed > 0.5:
                parts.append(f"速度{speed:.1f}m/s")

            steering = vehicle_state.get("steering", 0)
            if abs(steering) > 0.2:
                direction = "右" if steering > 0 else "左"
                parts.append(f"{direction}にステアリング中")

            mode = vehicle_state.get("mode", "")
            if mode:
                mode_map = {
                    "SENSOR_ONLY": "センサーモード",
                    "VISION": "ビジョンモード",
                    "FULL_AUTONOMY": "自動運転モード"
                }
                parts.append(mode_map.get(mode, f"{mode}モード"))

        if not parts:
            parts.append("走行中")

        return "。".join(parts) + "。"

    def run(self, max_cycles: Optional[int] = None):
        """
        実況ループ開始

        Args:
            max_cycles: 最大サイクル数（Noneなら無限ループ）
        """
        if not self.check_connection():
            print("Cannot start: JetRacer not connected")
            return

        print(f"Starting Vision Commentary Loop (interval: {self.interval_sec}s)")
        self.running = True

        try:
            while self.running:
                if max_cycles and self.stats.total_cycles >= max_cycles:
                    print(f"\nReached max cycles ({max_cycles})")
                    break

                cycle_start = time.time()

                print(f"\n{'='*60}")
                print(f"Cycle #{self.stats.total_cycles + 1}")
                print(f"{'='*60}")

                # 1フレーム処理
                result = self.process_single_frame()

                if result.success:
                    # コールバック呼び出し
                    if self.callback:
                        self.callback(result)

                    # コンソール出力
                    print(f"\n[やな] {result.yana_comment}")
                    print(f"[あゆ] {result.ayu_comment}")
                    print(f"\nVision: {result.vision_data}")
                    print(f"Timing: {result.timing}")
                    print(f"Total: {sum(result.timing.values()):.2f}s")
                else:
                    print(f"\nCycle failed: {result.error}")

                # 統計表示
                self._print_stats()

                # インターバル調整
                elapsed = time.time() - cycle_start
                sleep_time = max(0, self.interval_sec - elapsed)

                if sleep_time > 0:
                    print(f"\nSleeping {sleep_time:.2f}s...")
                    time.sleep(sleep_time)
                else:
                    print(f"\nProcessing took longer than interval ({elapsed:.2f}s > {self.interval_sec}s)")

        except KeyboardInterrupt:
            print("\n\nStopping Vision Commentary Loop...")
        finally:
            self.running = False
            self.print_final_stats()

    def stop(self):
        """実況ループ停止"""
        self.running = False

    def _print_stats(self):
        """統計表示"""
        print(f"\nStats:")
        print(f"  Success: {self.stats.successful_cycles}/{self.stats.total_cycles} ({self.stats.success_rate:.1f}%)")
        print(f"  Avg Detection: {self.stats.avg_detection_time:.2f}s")
        print(f"  Avg Generation: {self.stats.avg_generation_time:.2f}s")
        print(f"  Avg Total: {self.stats.avg_cycle_time:.2f}s")

    def print_final_stats(self):
        """最終統計表示"""
        print(f"\n{'='*60}")
        print("Final Statistics")
        print(f"{'='*60}")
        print(f"Total Cycles: {self.stats.total_cycles}")
        print(f"Successful: {self.stats.successful_cycles}")
        print(f"Failed: {self.stats.failed_cycles}")
        print(f"Success Rate: {self.stats.success_rate:.1f}%")
        print(f"\nAverage Timings:")
        print(f"  Detection: {self.stats.avg_detection_time:.2f}s")
        print(f"  Generation: {self.stats.avg_generation_time:.2f}s")
        print(f"  Total: {self.stats.avg_cycle_time:.2f}s")

    def reset_stats(self):
        """統計をリセット"""
        self.stats = LoopStats()
        self.conversation_history.clear()

    def get_stats(self) -> Dict[str, Any]:
        """統計を辞書で取得"""
        return {
            "total_cycles": self.stats.total_cycles,
            "successful_cycles": self.stats.successful_cycles,
            "failed_cycles": self.stats.failed_cycles,
            "success_rate": self.stats.success_rate,
            "avg_detection_time": self.stats.avg_detection_time,
            "avg_generation_time": self.stats.avg_generation_time,
            "avg_cycle_time": self.stats.avg_cycle_time
        }
