#!/usr/bin/env python3
"""
JetRacer Live Commentary v2.1 - リアルタイム実況スクリプト

JetRacerのセンサーデータをリアルタイムで取得し、
やな（Edge AI）とあゆ（Cloud AI）が実況します。

v2.1 新機能:
- DuoSignals: スレッドセーフな状態共有
- NoveltyGuard: 話題ループ検知と戦略ローテーション
- SilenceController: 高速走行・緊張シーンでの沈黙制御
- speak_v2: 統合された発話生成メソッド
- PromptBuilder: 優先度ベースのプロンプト構築

使用方法:
    python scripts/run_jetracer_live.py [--url URL] [--interval SECONDS] [--turns N]

環境変数:
    JETRACER_URL: JetRacer APIのURL（デフォルト: http://192.168.1.65:8000）
"""
import argparse
import time
import sys
import os
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.jetracer_client import JetRacerClient, JetRacerState, load_config
from src.jetracer_provider import JetRacerProvider, DataMode, VisionData
from src.character import Character
from src.director import Director

# v2.1 imports
from src.signals import DuoSignals, SignalEvent, EventType
from src.novelty_guard import NoveltyGuard
from src.silence_controller import SilenceController, SilenceAction
from src.config import config as app_config


class LiveCommentarySession:
    """
    v2.1 ライブ実況セッション

    従来のrun_jetracer_live.pyの機能を維持しつつ、
    v2.1のコンポーネントを統合
    """

    def __init__(
        self,
        jetracer_url: str = "http://192.168.1.65:8000",
        data_mode: DataMode = DataMode.VISION,
        turns_per_frame: int = 4,
        interval: float = 3.0,
        use_director: bool = True,
        fact_check: bool = True,
        log_to_file: bool = True
    ):
        """
        Args:
            jetracer_url: JetRacer APIのURL
            data_mode: データモード (SENSOR_ONLY, VISION, FULL_AUTONOMY)
            turns_per_frame: 1フレームあたりの対話ターン数
            interval: フレーム間隔（秒）
            use_director: ディレクター評価を使用するか
            fact_check: ファクトチェックを有効にするか
            log_to_file: ファイルにログを保存するか
        """
        self.jetracer_url = jetracer_url
        self.data_mode = data_mode
        self.turns_per_frame = turns_per_frame
        self.interval = interval
        self.use_director = use_director
        self.fact_check = fact_check
        self.log_to_file = log_to_file

        # v2.1 コンポーネント初期化
        DuoSignals.reset_instance()
        self.signals = DuoSignals()
        self.novelty_guard = NoveltyGuard()
        self.silence_controller = SilenceController()

        # キャラクター初期化
        self.char_a = Character("A")
        self.char_b = Character("B")

        # ディレクター（オプション）
        self.director = Director() if use_director else None

        # JetRacerクライアント（後で初期化）
        self.client: Optional[JetRacerClient] = None
        self.provider: Optional[JetRacerProvider] = None

        # セッション状態
        self.session_id = f"live_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.history: List[Dict[str, Any]] = []
        self.frame_count = 0
        self.total_turns = 0
        self.silence_count = 0
        self.loop_detections = 0
        self.errors = 0

        # ログファイル
        self.log_file = None
        if log_to_file:
            log_dir = app_config.log_dir / "live_sessions"
            log_dir.mkdir(parents=True, exist_ok=True)
            self.log_file = log_dir / f"{self.session_id}.jsonl"

    def connect(self) -> bool:
        """JetRacerに接続"""
        print(f"🔌 Connecting to JetRacer at {self.jetracer_url}...")
        try:
            self.client = JetRacerClient(self.jetracer_url, timeout=5.0)
            status = self.client.get_status()

            if not status:
                print("   ❌ Connection failed: No response")
                return False

            self.provider = JetRacerProvider(self.client, self.data_mode)

            print(f"   ✅ Connected")
            print(f"   Mode: {status.get('mode', 'unknown')}")
            print(f"   Data Mode: {self.data_mode.value}")

            return True

        except Exception as e:
            print(f"   ❌ Connection error: {e}")
            return False

    def _update_signals(self, sensor: JetRacerState, vision: Optional[VisionData]) -> None:
        """センサーデータをDuoSignalsに反映"""
        # センサーイベント
        self.signals.update(SignalEvent(
            event_type=EventType.SENSOR,
            data={
                "speed": abs(sensor.throttle) * 3.0,  # 推定速度 (m/s)
                "steering": sensor.steering * 45,     # ステアリング角度 (度)
                "sensors": {
                    "distance": sensor.min_distance,
                    "temperature": sensor.temperature
                }
            }
        ))

        # VLM観測（VISIONモード時）
        if vision and vision.road_percentage > 0:
            self.signals.update(SignalEvent(
                event_type=EventType.VLM,
                data={
                    "facts": {
                        "road_percentage": f"{vision.road_percentage:.0f}%",
                        "inference_time": f"{vision.inference_time_ms:.0f}ms"
                    }
                }
            ))

    def _format_state_display(self, sensor: JetRacerState, vision: Optional[VisionData]) -> str:
        """状態表示用フォーマット"""
        parts = [
            f"🌡️ {sensor.temperature:.1f}°C",
            f"🎮 {sensor.throttle*100:+.0f}%",
            f"🔄 {sensor.steering*100:+.0f}%",
        ]

        if sensor.min_distance > 0:
            parts.append(f"📏 {sensor.min_distance}mm")

        if vision and vision.road_percentage > 0:
            parts.append(f"🛤️ {vision.road_percentage:.0f}%")
            parts.append(f"⚡ {vision.inference_time_ms:.0f}ms")

        return " | ".join(parts)

    def _log_event(self, event: Dict[str, Any]) -> None:
        """イベントをログファイルに保存"""
        if self.log_file:
            event["session_id"] = self.session_id
            event["timestamp"] = datetime.now().isoformat()
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(event, ensure_ascii=False) + '\n')

    def _generate_dialogue(self, frame_desc: str) -> List[Dict[str, Any]]:
        """1フレーム分の対話を生成"""
        dialogue = []

        for turn in range(self.turns_per_frame):
            # 交互に話者を切り替え
            speaker = self.char_a if turn % 2 == 0 else self.char_b
            speaker_name = "やな" if turn % 2 == 0 else "あゆ"

            # 直前の発話を取得
            last_utterance = dialogue[-1]["content"] if dialogue else (
                self.history[-1]["content"] if self.history else "（画面を見ている）"
            )

            # v2.1 speak_v2 で発話生成
            result = speaker.speak_v2(
                last_utterance=last_utterance,
                context={"history": self.history[-5:] + dialogue},
                frame_description=frame_desc
            )

            if result["type"] == "speech":
                content = result["content"]
                debug = result.get("debug", {})

                dialogue.append({
                    "speaker": speaker_name,
                    "content": content,
                    "loop_detected": debug.get("loop_detected", False),
                    "strategy": debug.get("strategy"),
                    "unfilled_slots": debug.get("unfilled_slots", [])
                })

                # ループ検知カウント
                if debug.get("loop_detected"):
                    self.loop_detections += 1

                self.total_turns += 1

        return dialogue

    def run_frame(self) -> bool:
        """1フレームの処理を実行"""
        if not self.provider:
            return False

        try:
            # センサーデータ取得
            full_state = self.provider.fetch()

            if not full_state.valid or full_state.sensor is None:
                print("   ⚠️ Sensor data unavailable")
                self.errors += 1
                return False

            sensor = full_state.sensor
            vision = full_state.vision

            # DuoSignals更新
            self._update_signals(sensor, vision)

            # 状態表示
            state_display = self._format_state_display(sensor, vision)
            print(f"\n📊 {state_display}")

            # フレーム説明生成
            frame_desc = self.provider.to_frame_description(full_state)
            print(f"📝 {frame_desc[:70]}...")

            # 沈黙チェック
            state = self.signals.snapshot()
            silence = self.silence_controller.should_silence(state)

            if silence:
                self._handle_silence(silence)
                return True

            # 対話生成
            dialogue = self._generate_dialogue(frame_desc)

            # 対話表示
            print(f"\n💬 Dialogue:")
            for d in dialogue:
                print(f"   👧 {d['speaker']}: {d['content']}")
                if d.get("loop_detected"):
                    print(f"      ⚠️ Loop detected → {d.get('strategy')}")

                # 履歴に追加
                self.history.append({
                    "speaker": d["speaker"],
                    "content": d["content"],
                    "timestamp": datetime.now().isoformat()
                })

            # ログ保存
            self._log_event({
                "event": "dialogue",
                "frame": self.frame_count,
                "frame_description": frame_desc,
                "dialogue": dialogue
            })

            self.frame_count += 1
            return True

        except Exception as e:
            print(f"   ❌ Frame error: {e}")
            self.errors += 1
            return False

    def _handle_silence(self, silence: SilenceAction) -> None:
        """沈黙を処理"""
        print(f"\n🤫 Silence: {silence.silence_type.value} ({silence.duration_seconds}s)")

        self.silence_count += 1
        self._log_event({
            "event": "silence",
            "frame": self.frame_count,
            "type": silence.silence_type.value,
            "duration": silence.duration_seconds
        })

        # 沈黙時間を待機
        time.sleep(silence.duration_seconds)
        self.frame_count += 1

    def run(self, max_frames: Optional[int] = None) -> None:
        """メインループを実行"""
        print("\n" + "=" * 60)
        print("🎙️ JetRacer Live Commentary v2.1")
        print("=" * 60)
        print(f"   Session: {self.session_id}")
        print(f"   Interval: {self.interval}s")
        print(f"   Turns per frame: {self.turns_per_frame}")
        print(f"   Max frames: {max_frames or 'unlimited'}")
        print("=" * 60)
        print("\n🎬 Starting commentary... (Ctrl+C to stop)")

        try:
            while True:
                if max_frames and self.frame_count >= max_frames:
                    print(f"\n✅ Reached max frames ({max_frames})")
                    break

                self.run_frame()
                time.sleep(self.interval)

        except KeyboardInterrupt:
            print("\n\n⏹️ Stopped by user")

        finally:
            self._print_summary()

    def _print_summary(self) -> None:
        """セッションサマリーを表示"""
        print("\n" + "=" * 60)
        print("📊 Session Summary")
        print("=" * 60)
        print(f"   Session ID: {self.session_id}")
        print(f"   Total frames: {self.frame_count}")
        print(f"   Total turns: {self.total_turns}")
        print(f"   Silences: {self.silence_count}")
        print(f"   Loop detections: {self.loop_detections}")
        print(f"   Errors: {self.errors}")
        print(f"   History length: {len(self.history)}")

        if self.log_file:
            print(f"   Log file: {self.log_file}")

        if self.history:
            print(f"\n📝 Last 4 utterances:")
            for h in self.history[-4:]:
                print(f"   {h['speaker']}: {h['content'][:50]}...")

        print("=" * 60)


def main():
    # 設定読み込み（config.yaml）
    config = load_config()
    jetracer_config = config.get("jetracer", {})
    default_host = jetracer_config.get("host", "192.168.1.65")
    default_port = jetracer_config.get("port", 8000)
    default_url = f"http://{default_host}:{default_port}"

    commentary_config = config.get("commentary", {})
    default_interval = commentary_config.get("interval", 3.0)
    default_turns = commentary_config.get("turns_per_frame", 4)

    parser = argparse.ArgumentParser(
        description="JetRacer Live Commentary v2.1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # 基本実行
    python scripts/run_jetracer_live.py

    # カスタム設定
    python scripts/run_jetracer_live.py --url http://192.168.1.65:8000 --interval 2 --turns 4

    # 10フレームで終了
    python scripts/run_jetracer_live.py --frames 10

    # センサーのみモード
    python scripts/run_jetracer_live.py --mode sensor_only
        """
    )

    parser.add_argument("--url", "-u",
                        default=default_url,
                        help=f"JetRacer API URL (default: {default_url})")
    parser.add_argument("--interval", "-i", type=float,
                        default=default_interval,
                        help=f"Update interval in seconds (default: {default_interval})")
    parser.add_argument("--turns", "-t", type=int,
                        default=default_turns,
                        help=f"Conversation turns per frame (default: {default_turns})")
    parser.add_argument("--frames", "-f", type=int,
                        default=None,
                        help="Maximum frames to process (default: unlimited)")
    parser.add_argument("--mode", "-m",
                        choices=["sensor_only", "vision", "full_autonomy"],
                        default="vision",
                        help="Data mode (default: vision)")
    parser.add_argument("--no-director", action="store_true",
                        help="Disable director evaluation")
    parser.add_argument("--no-log", action="store_true",
                        help="Disable file logging")

    args = parser.parse_args()

    # DataMode変換
    mode_map = {
        "sensor_only": DataMode.SENSOR_ONLY,
        "vision": DataMode.VISION,
        "full_autonomy": DataMode.FULL_AUTONOMY
    }
    data_mode = mode_map[args.mode]

    # セッション作成
    session = LiveCommentarySession(
        jetracer_url=args.url,
        data_mode=data_mode,
        turns_per_frame=args.turns,
        interval=args.interval,
        use_director=not args.no_director,
        log_to_file=not args.no_log
    )

    # 接続
    if not session.connect():
        print("\n❌ Failed to connect to JetRacer")
        sys.exit(1)

    # 実行
    session.run(max_frames=args.frames)


if __name__ == "__main__":
    main()
