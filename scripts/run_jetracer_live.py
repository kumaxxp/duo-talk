#!/usr/bin/env python3
"""
JetRacer Live Commentary v3.0 - UnifiedPipeline統合版

JetRacerのセンサーデータをリアルタイムで取得し、
やな（Edge AI）とあゆ（Cloud AI）が実況します。

v3.0 変更点:
- UnifiedPipeline.run_continuous() を使用
- LiveCommentarySession を簡素化
- 重複コンポーネント（NoveltyGuard等）をUnifiedPipelineに委譲

使用方法:
    python scripts/run_jetracer_live.py [--url URL] [--interval SECONDS] [--frames N]

環境変数:
    JETRACER_URL: JetRacer APIのURL（デフォルト: http://192.168.1.65:8000）
"""
import argparse
import sys
import os
from datetime import datetime
from typing import Optional

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.unified_pipeline import UnifiedPipeline
from src.input_source import InputBundle, InputSource, SourceType
from src.jetracer_client import JetRacerClient, load_config
from src.jetracer_provider import JetRacerProvider, DataMode
from src.config import config as app_config


class JetRacerLiveSession:
    """
    v3.0 ライブ実況セッション（UnifiedPipelineベース）

    従来のLiveCommentarySessionを簡素化し、
    UnifiedPipeline.run_continuous()に委譲。
    """

    def __init__(
        self,
        jetracer_url: str = "http://192.168.1.65:8000",
        data_mode: DataMode = DataMode.VISION,
        turns_per_frame: int = 4,
        interval: float = 3.0,
    ):
        """
        Args:
            jetracer_url: JetRacer APIのURL
            data_mode: データモード (SENSOR_ONLY, VISION, FULL_AUTONOMY)
            turns_per_frame: 1フレームあたりの対話ターン数
            interval: フレーム間隔（秒）
        """
        self.jetracer_url = jetracer_url
        self.data_mode = data_mode
        self.turns_per_frame = turns_per_frame
        self.interval = interval

        # JetRacerクライアント（後で初期化）
        self.client: Optional[JetRacerClient] = None
        self.provider: Optional[JetRacerProvider] = None

        # UnifiedPipeline（後で初期化）
        self.pipeline: Optional[UnifiedPipeline] = None

        # 停止フラグ
        self._stop_requested = False

        # セッションID
        self.session_id = f"live_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

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

            # UnifiedPipeline初期化（JetRacerモード強制）
            self.pipeline = UnifiedPipeline(
                jetracer_client=self.client,
                jetracer_mode=True,
            )

            print(f"   ✅ Connected")
            print(f"   Mode: {status.get('mode', 'unknown')}")
            print(f"   Data Mode: {self.data_mode.value}")

            return True

        except Exception as e:
            print(f"   ❌ Connection error: {e}")
            return False

    def _create_input_bundle(self) -> Optional[InputBundle]:
        """JetRacerから入力バンドルを生成"""
        if self._stop_requested:
            return None

        sources = []

        # センサーデータは常に含める
        sources.append(InputSource(source_type=SourceType.JETRACER_SENSOR))

        # VISIONモード以上ならカメラも含める
        if self.data_mode in (DataMode.VISION, DataMode.FULL_AUTONOMY):
            sources.append(InputSource(source_type=SourceType.JETRACER_CAM0))

        return InputBundle(sources=sources)

    def _event_handler(self, event_type: str, data: dict):
        """イベントハンドラ"""
        if event_type == "session_start":
            print(f"\n🎬 Session started: {data.get('run_id')}")
        elif event_type == "narration_start":
            pass  # フレーム開始は静かに
        elif event_type == "speak":
            speaker = data.get("speaker_name", "?")
            text = data.get("text", "")
            preview = text[:60] + "..." if len(text) > 60 else text
            status = data.get("evaluation_status", "")
            print(f"   💬 {speaker}: {preview}")
            if status and status != "PASS":
                print(f"      📋 Director: {status}")
        elif event_type == "frame_complete":
            frame = data.get("frame", 0)
            turns = data.get("turns", 0)
            print(f"   📷 Frame {frame} complete ({turns} turns)")
        elif event_type == "session_end":
            frames = data.get("total_frames", 0)
            turns = data.get("total_turns", 0)
            print(f"\n✅ Session ended: {frames} frames, {turns} turns")

    def _stop_check(self) -> bool:
        """停止判定"""
        return self._stop_requested

    def run(self, max_frames: Optional[int] = None) -> None:
        """メインループを実行"""
        if not self.pipeline:
            print("❌ Not connected. Call connect() first.")
            return

        print("\n" + "=" * 60)
        print("🎙️ JetRacer Live Commentary v3.0 (UnifiedPipeline)")
        print("=" * 60)
        print(f"   Session: {self.session_id}")
        print(f"   Interval: {self.interval}s")
        print(f"   Turns per frame: {self.turns_per_frame}")
        print(f"   Max frames: {max_frames or 'unlimited'}")
        print("=" * 60)
        print("\n🎬 Starting... (Ctrl+C to stop)")

        try:
            result = self.pipeline.run_continuous(
                input_generator=self._create_input_bundle,
                max_frames=max_frames,
                frame_interval=self.interval,
                turns_per_frame=self.turns_per_frame,
                run_id=self.session_id,
                event_callback=self._event_handler,
                stop_callback=self._stop_check,
            )

            # サマリー表示
            self._print_summary(result)

        except KeyboardInterrupt:
            print("\n\n⏹️ Stopped by user")
            self._stop_requested = True

    def _print_summary(self, result) -> None:
        """セッションサマリーを表示"""
        print("\n" + "=" * 60)
        print("📊 Session Summary")
        print("=" * 60)
        print(f"   Run ID: {result.run_id}")
        print(f"   Status: {result.status}")
        print(f"   Total frames: {result.metadata.get('total_frames', 0)}")
        print(f"   Total turns: {result.metadata.get('total_turns', 0)}")

        if result.dialogue:
            print(f"\n📝 Last 4 utterances:")
            for turn in result.dialogue[-4:]:
                text = turn.text[:50] + "..." if len(turn.text) > 50 else turn.text
                print(f"   {turn.speaker_name}: {text}")

        if result.error:
            print(f"\n❌ Error: {result.error}")

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
        description="JetRacer Live Commentary v3.0 (UnifiedPipeline)",
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
                        help=f"Frame interval in seconds (default: {default_interval})")
    parser.add_argument("--turns", "-t", type=int,
                        default=default_turns,
                        help=f"Turns per frame (default: {default_turns})")
    parser.add_argument("--frames", "-f", type=int,
                        default=None,
                        help="Max frames to process (default: unlimited)")
    parser.add_argument("--mode", "-m",
                        choices=["sensor_only", "vision", "full_autonomy"],
                        default="vision",
                        help="Data mode (default: vision)")

    args = parser.parse_args()

    # DataMode変換
    mode_map = {
        "sensor_only": DataMode.SENSOR_ONLY,
        "vision": DataMode.VISION,
        "full_autonomy": DataMode.FULL_AUTONOMY
    }
    data_mode = mode_map[args.mode]

    # セッション作成
    session = JetRacerLiveSession(
        jetracer_url=args.url,
        data_mode=data_mode,
        turns_per_frame=args.turns,
        interval=args.interval,
    )

    # 接続
    if not session.connect():
        print("\n❌ Failed to connect to JetRacer")
        sys.exit(1)

    # 実行
    session.run(max_frames=args.frames)


if __name__ == "__main__":
    main()
