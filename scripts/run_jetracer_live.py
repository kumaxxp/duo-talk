#!/usr/bin/env python3
"""
JetRacer Live Commentary - リアルタイム実況スクリプト

JetRacerのセンサーデータをリアルタイムで取得し、
やな（Edge AI）とあゆ（Cloud AI）が実況します。

使用方法:
    python scripts/run_jetracer_live.py [--url URL] [--interval SECONDS]

環境変数:
    JETRACER_URL: JetRacer APIのURL（デフォルト: http://localhost:8000）
"""
import argparse
import time
import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.jetracer_client import JetRacerClient, JetRacerState
from src.character import Character
from src.director import Director


def create_risk_instruction(risks: dict) -> str:
    """リスクレベルに応じたディレクター指示を生成"""
    overall = risks.get("overall", "low")
    
    if overall == "critical":
        return "緊急事態です。即座に対応を議論してください。"
    elif overall == "high":
        return "リスクが高まっています。注意を促してください。"
    elif overall == "medium":
        return "軽度の注意が必要です。状況を確認してください。"
    else:
        return None  # 特別な指示なし


def format_state_summary(state: JetRacerState) -> str:
    """状態サマリーを表示用にフォーマット"""
    lines = []
    lines.append(f"🌡️  温度: {state.temperature:.1f}°C")
    lines.append(f"🎮 スロットル: {state.throttle*100:+.0f}%")
    lines.append(f"🔄 ステアリング: {state.steering*100:+.0f}%")
    lines.append(f"📍 モード: {state.mode}")
    if state.min_distance > 0:
        lines.append(f"📏 前方距離: {state.min_distance}mm")
    return " | ".join(lines)


def main():
    parser = argparse.ArgumentParser(description="JetRacer Live Commentary")
    parser.add_argument("--url", "-u", 
                        default=os.getenv("JETRACER_URL", "http://localhost:8000"),
                        help="JetRacer API URL")
    parser.add_argument("--interval", "-i", type=float, default=3.0,
                        help="Update interval in seconds")
    parser.add_argument("--turns", "-t", type=int, default=4,
                        help="Number of conversation turns per frame")
    parser.add_argument("--dry-run", action="store_true",
                        help="Use mock data instead of real JetRacer")
    args = parser.parse_args()
    
    print("=" * 60)
    print("🚗 JetRacer Live Commentary")
    print("=" * 60)
    print(f"API URL: {args.url}")
    print(f"Interval: {args.interval}s")
    print(f"Turns per frame: {args.turns}")
    print("=" * 60)
    
    # キャラクター初期化
    print("\n📦 Loading characters...")
    try:
        char_a = Character("A")  # やな（Edge AI）
        char_b = Character("B")  # あゆ（Cloud AI）
        director = Director()
        print("✅ Characters loaded")
    except Exception as e:
        print(f"❌ Failed to load characters: {e}")
        return 1
    
    # JetRacerクライアント初期化
    if args.dry_run:
        print("\n🔧 Dry-run mode (using mock data)")
        client = None
    else:
        print(f"\n🔌 Connecting to JetRacer at {args.url}...")
        client = JetRacerClient(args.url)
        
        # 接続テスト
        test_data = client.get_status()
        if test_data:
            print("✅ Connected to JetRacer")
        else:
            print("⚠️  Could not connect to JetRacer (will retry)")
    
    print("\n" + "=" * 60)
    print("🎬 Starting live commentary (Ctrl+C to stop)")
    print("=" * 60 + "\n")
    
    frame_num = 0
    
    try:
        while True:
            frame_num += 1
            
            # センサーデータ取得
            if args.dry_run:
                # モックデータ
                state = JetRacerState(
                    temperature=42.0 + frame_num * 0.5,
                    throttle=0.5,
                    steering=0.1,
                    mode="auto",
                    min_distance=800 - frame_num * 50,
                    accel_x=0.2,
                    accel_y=0.1,
                    accel_z=9.8,
                    timestamp=time.time(),
                    valid=True
                )
                frame_desc = client.to_frame_description(state) if client else \
                    f"スロットル50%で走行中。温度{state.temperature:.0f}度。前方{state.min_distance}mmに物体。"
                risks = {"overall": "low", "temperature": "low", "collision": "medium"}
            else:
                state = client.fetch_and_parse()
                if not state.valid:
                    print(f"⚠️  Frame {frame_num}: Sensor data unavailable")
                    time.sleep(args.interval)
                    continue
                frame_desc = client.to_frame_description(state)
                risks = client.get_risk_level(state)
            
            # フレーム表示
            print(f"\n{'─' * 60}")
            print(f"📊 Frame {frame_num}")
            print(f"{'─' * 60}")
            print(format_state_summary(state))
            print(f"\n📝 状況: {frame_desc}")
            
            # リスク表示
            risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}
            print(f"⚠️  リスク: {risk_emoji.get(risks['overall'], '⚪')} {risks['overall'].upper()}")
            
            print(f"\n{'─' * 60}")
            
            # 会話ターン
            partner_speech = None
            risk_instruction = create_risk_instruction(risks)
            
            for turn in range(args.turns):
                # 話者決定（交互）
                if turn % 2 == 0:
                    speaker = char_a
                    speaker_name = "👧 やな"
                else:
                    speaker = char_b
                    speaker_name = "👧 あゆ"
                
                # 発言生成
                response = speaker.speak(
                    frame_description=frame_desc,
                    partner_speech=partner_speech,
                    director_instruction=risk_instruction if turn == 0 else None,
                )
                
                # ディレクター評価
                evaluation = director.evaluate_response(
                    frame_description=frame_desc,
                    speaker="A" if turn % 2 == 0 else "B",
                    response=response,
                    partner_previous_speech=partner_speech,
                    speaker_domains=speaker.domains,
                    frame_num=frame_num,
                )
                
                # リトライが必要な場合
                retry_count = 0
                while evaluation.status.name == "RETRY" and retry_count < 2:
                    retry_count += 1
                    response = speaker.speak(
                        frame_description=frame_desc,
                        partner_speech=partner_speech,
                        director_instruction=evaluation.suggestion,
                    )
                    evaluation = director.evaluate_response(
                        frame_description=frame_desc,
                        speaker="A" if turn % 2 == 0 else "B",
                        response=response,
                        partner_previous_speech=partner_speech,
                        speaker_domains=speaker.domains,
                        frame_num=frame_num,
                    )
                
                # 発言表示
                print(f"{speaker_name}: {response}")
                
                partner_speech = response
            
            # 次のフレームまで待機
            time.sleep(args.interval)
            
    except KeyboardInterrupt:
        print("\n\n" + "=" * 60)
        print("⏹️  Commentary stopped")
        print("=" * 60)
    
    finally:
        if client:
            client.close()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
