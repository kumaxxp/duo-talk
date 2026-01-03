"""
duo-talk Dashboard - JetRacer Live Commentary GUI

既存のrun_jetracer_live.pyロジックをGUIから呼び出す。
Timeline形式で会話を表示。
"""
from nicegui import ui
import asyncio
from pathlib import Path
import sys
from datetime import datetime

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.jetracer_client import load_config
from src.jetracer_provider import JetRacerProvider, DataMode
from src.character import Character
from src.director import Director


class DuoTalkDashboard:
    """duo-talk ダッシュボード"""

    def __init__(self):
        # 設定読み込み
        self.config = load_config()
        jetracer_config = self.config.get("jetracer", {})
        commentary_config = self.config.get("commentary", {})

        # 設定値
        self.interval = commentary_config.get("interval", 3.0)
        self.turns_per_frame = commentary_config.get("turns_per_frame", 4)
        self.data_mode = jetracer_config.get("data_mode", "vision")

        # 状態
        self.running = False
        self.provider = None
        self.char_a = None
        self.char_b = None
        self.director = None
        self.frame_count = 0

        # UI要素
        self.timeline_widget = None
        self.scroll_area = None
        self.placeholder = None
        self.status_label = None
        self.frame_info_label = None
        self.frame_desc_label = None
        self.start_btn = None
        self.stop_btn = None
        self.mode_select = None
        self.interval_input = None
        self.turns_input = None
        self._timer = None

    def create_ui(self):
        """UI作成"""
        ui.dark_mode(False)

        with ui.column().classes('w-full max-w-6xl mx-auto p-4 gap-4'):
            # ヘッダー
            with ui.row().classes('w-full items-center gap-4'):
                ui.label('🚗 duo-talk JetRacer Live').classes('text-2xl font-bold')
                self.status_label = ui.label('⏸ Stopped').classes('text-sm text-gray-500')

            # フレーム情報バー
            with ui.card().classes('w-full'):
                with ui.row().classes('w-full items-center gap-4'):
                    ui.label('📊').classes('text-lg')
                    self.frame_info_label = ui.label('--').classes('font-mono text-sm flex-grow')
                self.frame_desc_label = ui.label('--').classes('text-gray-600 text-sm')

            with ui.row().classes('w-full gap-4'):
                # 左: コントロールパネル
                with ui.card().classes('w-64 shrink-0'):
                    ui.label('🎛️ Control').classes('text-lg font-bold mb-2')

                    # モード選択
                    ui.label('Data Mode').classes('text-sm text-gray-600')
                    self.mode_select = ui.select(
                        options=['sensor_only', 'vision', 'full_autonomy'],
                        value=self.data_mode,
                        on_change=self._on_mode_change
                    ).classes('w-full')

                    # Interval
                    ui.label('Interval (sec)').classes('text-sm text-gray-600 mt-2')
                    self.interval_input = ui.number(
                        value=self.interval, min=1, max=30, step=1
                    ).classes('w-full')

                    # Turns
                    ui.label('Turns per frame').classes('text-sm text-gray-600 mt-2')
                    self.turns_input = ui.number(
                        value=self.turns_per_frame, min=1, max=10, step=1
                    ).classes('w-full')

                    # ボタン
                    with ui.row().classes('w-full gap-2 mt-4'):
                        self.start_btn = ui.button(
                            '▶ Start', on_click=self._start
                        ).props('color=green')
                        self.stop_btn = ui.button(
                            '⏹ Stop', on_click=self._stop
                        ).props('color=red disabled')

                    # 凡例
                    ui.separator().classes('my-4')
                    ui.label('Legend').classes('text-sm text-gray-600')
                    with ui.row().classes('gap-2 items-center'):
                        ui.badge('やな', color='pink').props('outline')
                        ui.label('Edge AI').classes('text-xs text-gray-500')
                    with ui.row().classes('gap-2 items-center'):
                        ui.badge('あゆ', color='purple').props('outline')
                        ui.label('Cloud AI').classes('text-xs text-gray-500')

                # 右: Timeline
                with ui.card().classes('flex-grow'):
                    ui.label('💬 Timeline').classes('text-lg font-bold mb-2')
                    with ui.scroll_area().classes('w-full h-96') as scroll:
                        self.scroll_area = scroll
                        with ui.timeline(side='right').classes('w-full') as timeline:
                            self.timeline_widget = timeline
                        self.placeholder = ui.label('Press Start to begin...').classes('text-gray-400 text-center w-full')

    def _on_mode_change(self, e):
        """モード変更"""
        self.data_mode = e.value
        ui.notify(f'Mode: {e.value}')

    async def _start(self):
        """実況開始"""
        print("[Dashboard] Start button clicked")
        self.running = True
        self.start_btn.props('disabled')
        self.stop_btn.props(remove='disabled')
        self.status_label.set_text('🔄 Initializing...')

        # 設定更新
        self.interval = float(self.interval_input.value)
        self.turns_per_frame = int(self.turns_input.value)
        print(f"[Dashboard] Interval: {self.interval}s, Turns: {self.turns_per_frame}")

        # 初期化
        try:
            # Provider
            print(f"[Dashboard] Creating JetRacerProvider with mode: {self.data_mode}")
            mode = DataMode(self.data_mode)
            self.provider = JetRacerProvider(mode=mode)
            print(f"[Dashboard] Provider created successfully")

            # キャラクター
            print("[Dashboard] Creating characters...")
            self.char_a = Character("A")  # やな（Edge AI）
            self.char_b = Character("B")  # あゆ（Cloud AI）
            print("[Dashboard] Characters created")

            # Director
            fact_check = self.config.get("commentary", {}).get("fact_check_enabled", False)
            self.director = Director(enable_fact_check=fact_check)
            print("[Dashboard] Director created")

            self.status_label.set_text('✅ Running')
            # タイムラインをクリア
            if self.timeline_widget:
                self.timeline_widget.clear()
            self.frame_count = 0

            # 初期メッセージ
            self._add_info_entry(f'Started at {datetime.now().strftime("%H:%M:%S")}')
            print("[Dashboard] Initial info entry added")

            # タイマー開始
            self._timer = ui.timer(self.interval, self._update_frame)
            print(f"[Dashboard] Timer started with interval {self.interval}s")

        except Exception as e:
            import traceback
            print(f"[Dashboard] Error during start: {e}")
            traceback.print_exc()
            self.status_label.set_text(f'❌ Error: {e}')
            self._add_error_entry(str(e))
            self.running = False
            self.start_btn.props(remove='disabled')
            self.stop_btn.props('disabled')

    async def _stop(self):
        """実況停止"""
        self.running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None

        if self.provider:
            self.provider.close()
            self.provider = None

        self.start_btn.props(remove='disabled')
        self.stop_btn.props('disabled')
        self.status_label.set_text('⏸ Stopped')
        self._add_info_entry(f'Stopped at {datetime.now().strftime("%H:%M:%S")}')

    async def _update_frame(self):
        """フレーム更新"""
        if not self.running or not self.provider:
            print("[Dashboard] _update_frame: not running or no provider")
            return

        self.frame_count += 1
        print(f"[Dashboard] Frame {self.frame_count} starting...")

        try:
            # データ取得
            print("[Dashboard] Fetching sensor data...")
            state = self.provider.fetch()

            if not state.valid:
                print(f"[Dashboard] Sensor data invalid: {state.error}")
                self._add_warning_entry('センサーデータ取得失敗')
                return
            print("[Dashboard] Sensor data fetched successfully")

            # フレーム情報更新
            sensor = state.sensor
            vision = state.vision

            info_parts = [
                f'Frame {self.frame_count}',
                f'🌡️ {sensor.temperature:.1f}°C',
                f'📏 {sensor.min_distance}mm',
                f'🎮 {sensor.throttle*100:+.0f}%',
            ]
            if vision and vision.road_percentage > 0:
                info_parts.append(f'🛤️ {vision.road_percentage:.1f}%')
                info_parts.append(f'⚡ {vision.inference_time_ms:.0f}ms')

            self.frame_info_label.set_text(' | '.join(info_parts))

            # フレーム説明
            frame_desc = self.provider.to_frame_description(state)
            self.frame_desc_label.set_text(f'📝 {frame_desc}')

            # フレームヘッダーをTimelineに追加
            print(f"[Dashboard] Adding frame entry for Frame {self.frame_count}")
            self._add_frame_entry(f'Frame {self.frame_count}', frame_desc)

            # 会話ターン
            partner_speech = None
            for turn in range(self.turns_per_frame):
                if not self.running:
                    break

                # 話者決定（交互）
                if turn % 2 == 0:
                    speaker = self.char_a
                    speaker_id = 'yana'
                else:
                    speaker = self.char_b
                    speaker_id = 'ayu'

                # 発言生成（非同期で実行）
                print(f"[Dashboard] Generating response for {speaker_id} (turn {turn + 1})...")
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda s=speaker, fd=frame_desc, ps=partner_speech: s.speak(
                        frame_description=fd,
                        partner_speech=ps,
                    )
                )
                print(f"[Dashboard] {speaker_id} response: {response[:50]}...")

                if speaker_id == 'yana':
                    self._add_yana_entry(response)
                else:
                    self._add_ayu_entry(response)

                # 次のターンのために保存
                partner_speech = response

            print(f"[Dashboard] Frame {self.frame_count} completed")

        except Exception as e:
            import traceback
            print(f"[Dashboard] Error in _update_frame: {e}")
            traceback.print_exc()
            self._add_error_entry(str(e))

    def _scroll_to_bottom(self):
        """スクロールを最下部に移動"""
        if self.scroll_area:
            self.scroll_area.scroll_to(percent=1.0)

    def _hide_placeholder(self):
        """プレースホルダーを非表示"""
        if self.placeholder:
            self.placeholder.set_visibility(False)

    def _add_frame_entry(self, title: str, subtitle: str = None):
        """フレームエントリ追加"""
        self._hide_placeholder()
        truncated = subtitle[:60] + '...' if subtitle and len(subtitle) > 60 else subtitle
        with self.timeline_widget:
            ui.timeline_entry(title=title, subtitle=truncated, icon='videocam', color='blue')
        self._scroll_to_bottom()

    def _add_yana_entry(self, text: str):
        """やなエントリ追加"""
        self._hide_placeholder()
        with self.timeline_widget:
            with ui.timeline_entry(title='やな', icon='memory', color='pink'):
                ui.label(text).classes('text-sm')
        self._scroll_to_bottom()

    def _add_ayu_entry(self, text: str):
        """あゆエントリ追加"""
        self._hide_placeholder()
        with self.timeline_widget:
            with ui.timeline_entry(title='あゆ', icon='cloud', color='purple'):
                ui.label(text).classes('text-sm')
        self._scroll_to_bottom()

    def _add_warning_entry(self, text: str):
        """警告エントリ追加"""
        self._hide_placeholder()
        with self.timeline_widget:
            with ui.timeline_entry(title='Warning', icon='warning', color='yellow'):
                ui.label(text).classes('text-sm text-yellow-600')
        self._scroll_to_bottom()

    def _add_error_entry(self, text: str):
        """エラーエントリ追加"""
        self._hide_placeholder()
        with self.timeline_widget:
            with ui.timeline_entry(title='Error', icon='error', color='red'):
                ui.label(text).classes('text-sm text-red-600')
        self._scroll_to_bottom()

    def _add_info_entry(self, text: str):
        """情報エントリ追加"""
        self._hide_placeholder()
        with self.timeline_widget:
            with ui.timeline_entry(title='Info', icon='info', color='grey'):
                ui.label(text).classes('text-sm')
        self._scroll_to_bottom()


def main():
    dashboard = DuoTalkDashboard()
    dashboard.create_ui()
    ui.run(title='duo-talk Dashboard', port=8080, reload=False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
