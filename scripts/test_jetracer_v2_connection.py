#!/usr/bin/env python3
"""
JetRacer v2.1 接続テスト
- JetRacer APIへの接続確認
- センサーデータ取得
- DuoSignalsへの流し込みテスト
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.jetracer_client import JetRacerClient, JetRacerState
from src.jetracer_provider import JetRacerProvider, DataMode
from src.signals import DuoSignals, SignalEvent, EventType


def test_connection(url: str = "http://192.168.1.65:8000") -> bool:
    """接続テスト"""
    print(f"🔌 Connecting to {url}...")

    client = JetRacerClient(url, timeout=5.0)

    try:
        data = client.get_all_sensors()
        if data:
            print("✅ Connection successful!")
            print(f"   Raw data keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
            return True
        else:
            print("❌ Connection failed - no data returned")
            return False
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False


def test_sensor_fetch(url: str = "http://192.168.1.65:8000") -> JetRacerState:
    """センサーデータ取得テスト"""
    print("\n📊 Fetching sensor data...")

    client = JetRacerClient(url, timeout=5.0)
    state = client.fetch_and_parse()

    if state.valid:
        print("✅ Sensor data received!")
        print(f"   Temperature: {state.temperature:.1f}°C")
        print(f"   Throttle: {state.throttle*100:.0f}%")
        print(f"   Steering: {state.steering*100:.0f}%")
        print(f"   Mode: {state.mode}")
        print(f"   Min Distance: {state.min_distance}mm")
        print(f"\n📝 Frame Description:")
        print(f"   {client.to_frame_description(state)}")
    else:
        print(f"❌ Sensor fetch failed: {state.error}")

    client.close()
    return state


def test_signals_integration(state: JetRacerState) -> None:
    """DuoSignalsへの統合テスト"""
    print("\n🔗 Testing DuoSignals integration...")

    DuoSignals.reset_instance()
    signals = DuoSignals()

    # センサーデータをSignalEventに変換して流し込み
    signals.update(SignalEvent(
        event_type=EventType.SENSOR,
        data={
            "speed": abs(state.throttle) * 3.0,  # 速度推定（仮）
            "steering": state.steering * 45,  # 角度変換（仮）
            "sensors": {
                "distance": state.min_distance,
                "temperature": state.temperature
            }
        }
    ))

    # モード変更イベント
    mode_map = {"manual": "SENSOR_ONLY", "auto": "FULL_AUTONOMY"}
    signals.update(SignalEvent(
        event_type=EventType.MODE_CHANGE,
        data={"mode": mode_map.get(state.mode, "SENSOR_ONLY")}
    ))

    # スナップショット確認
    snapshot = signals.snapshot()
    print("✅ DuoSignals updated!")
    print(f"   Mode: {snapshot.jetracer_mode}")
    print(f"   Speed: {snapshot.current_speed:.2f}")
    print(f"   Steering: {snapshot.steering_angle:.1f}°")
    print(f"   Sensors: {snapshot.distance_sensors}")
    print(f"   Stale: {signals.is_stale()}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="JetRacer v2.1 Connection Test")
    parser.add_argument("--url", "-u", default="http://192.168.1.65:8000",
                        help="JetRacer API URL")
    args = parser.parse_args()

    url = args.url

    print("=" * 60)
    print("🚗 JetRacer v2.1 Connection Test")
    print("=" * 60)

    # 1. 接続テスト
    if not test_connection(url):
        print("\n⚠️  Cannot proceed without connection")
        return 1

    # 2. センサーデータ取得
    state = test_sensor_fetch(url)
    if not state.valid:
        print("\n⚠️  Cannot proceed without sensor data")
        return 1

    # 3. DuoSignals統合
    test_signals_integration(state)

    print("\n" + "=" * 60)
    print("✅ All connection tests passed!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
