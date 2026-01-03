"""
duo-talk Dashboard - JetRacer Live Commentary GUI

既存のrun_jetracer_live.pyロジックをGUIから呼び出す。
Timeline形式で会話を表示。Director評価とReact GUI互換ログ出力。
"""
from nicegui import ui
import asyncio
from pathlib import Path
import sys
from datetime import datetime
from typing import Optional

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.jetracer_client import load_config
from src.jetracer_provider import JetRacerProvider, DataMode
from src.character import Character
from src.director import Director
from src.logger import get_logger
from src.types import DirectorEvaluation


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
        self.turn_count = 0
        self.run_id = None
        self.logger = get_logger()
        self.current_frame_desc = ""

        # ターンデータ保存（詳細モーダル用）
        self.turn_data = {}  # {turn_num: {speaker, text, director_status, director_reason, ...}}

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
        self.detail_dialog = None
        self.detail_content = None

    def create_ui(self):
        """UI作成"""
        ui.dark_mode(False)

        # キャラクターアイコンのパス
        self.icon_yana = str(project_root / 'icon' / 'yana_face.png')
        self.icon_ayu = str(project_root / 'icon' / 'ayu_face.png')

        with ui.column().classes('w-full p-4 gap-4'):  # 幅制限なし
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

            with ui.row().classes('w-full gap-4 flex-nowrap'):
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

                    # 凡例（TurnCard風の色）
                    ui.separator().classes('my-4')
                    ui.label('Legend').classes('text-sm text-gray-600')
                    with ui.row().classes('gap-2 items-center'):
                        ui.badge('やな', color='#f43f5e').classes('text-white')
                        ui.label('Edge AI').classes('text-xs text-gray-500')
                    with ui.row().classes('gap-2 items-center'):
                        ui.badge('あゆ', color='#0ea5e9').classes('text-white')
                        ui.label('Cloud AI').classes('text-xs text-gray-500')

                # 右: カードリスト（TurnCard風）
                with ui.card().classes('flex-grow min-w-[1000px]'):
                    ui.label('💬 Timeline').classes('text-lg font-bold mb-2')
                    with ui.scroll_area().classes('w-full h-[800px]') as scroll:
                        self.scroll_area = scroll
                        with ui.column().classes('w-full gap-3') as cards_container:
                            self.timeline_widget = cards_container
                        self.placeholder = ui.label('Press Start to begin...').classes('text-gray-400 text-center w-full')

        # 詳細モーダル
        with ui.dialog() as dialog, ui.card().classes('w-[900px] max-h-[80vh]'):
            self.detail_dialog = dialog
            with ui.column().classes('w-full gap-4') as content:
                self.detail_content = content

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
            self.turn_count = 0
            self.turn_data = {}
            self.current_frame_desc = ""

            # Director の TopicState をリセット
            self.director.reset_topic_state()

            # run_id生成とログ開始
            self.run_id = f"dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.logger.log_run_start(
                run_id=self.run_id,
                frame_count=0,
                metadata={"mode": self.data_mode, "interval": self.interval, "turns_per_frame": self.turns_per_frame}
            )
            print(f"[Dashboard] Logging started: {self.run_id}")

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

        # ログ終了
        if self.run_id:
            self.logger.log_run_end(run_id=self.run_id, total_turns=self.turn_count)
            print(f"[Dashboard] Logging ended: {self.run_id}, total_turns={self.turn_count}")
            self.run_id = None

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
            self.current_frame_desc = frame_desc
            self.frame_desc_label.set_text(f'📝 {frame_desc}')

            # フレームヘッダーをTimelineに追加
            print(f"[Dashboard] Adding frame entry for Frame {self.frame_count}")
            self._add_frame_entry(f'Frame {self.frame_count}', frame_desc)

            # 会話ターン
            partner_speech = None
            dialogue_history = []

            for turn in range(self.turns_per_frame):
                if not self.running:
                    break

                # 話者決定（交互）
                if turn % 2 == 0:
                    speaker = self.char_a
                    speaker_id = 'yana'
                    speaker_code = 'A'
                else:
                    speaker = self.char_b
                    speaker_id = 'ayu'
                    speaker_code = 'B'

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

                # Director評価（非同期で実行）
                print(f"[Dashboard] Evaluating with Director...")
                director_eval = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.director.evaluate_response(
                        frame_description=frame_desc,
                        speaker=speaker_code,
                        response=response,
                        partner_previous_speech=partner_speech,
                        conversation_history=dialogue_history,
                        turn_number=self.turn_count + 1,
                        frame_num=self.frame_count,
                    )
                )

                director_status = director_eval.status.name if director_eval else "PASS"
                director_reason = director_eval.reason if director_eval else ""
                director_guidance = director_eval.next_instruction if director_eval else ""
                beat = director_eval.beat_stage if director_eval else ""
                focus_hook = director_eval.focus_hook if director_eval else ""

                print(f"[Dashboard] Director: {director_status} - {director_reason[:30]}...")

                # ターンカウント更新
                self.turn_count += 1

                # ターンデータ保存（詳細モーダル用）
                self.turn_data[self.turn_count] = {
                    'speaker': speaker_code,
                    'speaker_id': speaker_id,
                    'text': response,
                    'frame': self.frame_count,
                    'frame_desc': frame_desc,
                    'director_status': director_status,
                    'director_reason': director_reason,
                    'director_guidance': director_guidance,
                    'beat': beat,
                }

                # React GUI互換ログ出力: speak event
                self.logger.log_event({
                    "event": "speak",
                    "run_id": self.run_id,
                    "turn": self.turn_count,
                    "speaker": speaker_code,
                    "text": response,
                    "beat": beat,
                    "ts": datetime.now().isoformat(),
                })

                # React GUI互換ログ出力: director event
                self.logger.log_event({
                    "event": "director",
                    "run_id": self.run_id,
                    "turn": self.turn_count,
                    "beat": beat,
                    "status": director_status,
                    "reason": director_reason,
                    "guidance": director_guidance,
                    "ts": datetime.now().isoformat(),
                })

                # Timeline表示（Director情報付き）
                if speaker_id == 'yana':
                    self._add_yana_entry_with_director(
                        response, self.turn_count, director_status, director_reason
                    )
                else:
                    self._add_ayu_entry_with_director(
                        response, self.turn_count, director_status, director_reason
                    )

                # 会話履歴に追加
                dialogue_history.append((speaker_code, response))

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
        """フレームエントリ追加（カード形式）"""
        self._hide_placeholder()
        truncated = subtitle[:80] + '...' if subtitle and len(subtitle) > 80 else subtitle
        with self.timeline_widget:
            with ui.element('div').classes('w-full p-3 bg-blue-50 border border-blue-200 rounded-lg'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('videocam').classes('text-blue-500')
                    ui.label(title).classes('font-bold text-blue-700')
                if truncated:
                    ui.label(truncated).classes('text-sm text-blue-600 mt-1')
        self._scroll_to_bottom()

    def _add_yana_entry(self, text: str):
        """やなエントリ追加（旧形式、互換性用）"""
        self._add_yana_entry_with_director(text, 0, "PASS", "")

    def _add_ayu_entry(self, text: str):
        """あゆエントリ追加（旧形式、互換性用）"""
        self._add_ayu_entry_with_director(text, 0, "PASS", "")

    def _get_director_badge_style(self, status: str) -> tuple:
        """Director判定に応じたバッジスタイルを返す"""
        if status == "PASS":
            return ("✓", "green", "bg-green-100 text-green-700")
        elif status == "RETRY":
            return ("🔄", "orange", "bg-amber-100 text-amber-700")
        else:  # MODIFY
            return ("⚠️", "red", "bg-red-100 text-red-700")

    def _add_yana_entry_with_director(self, text: str, turn_num: int, director_status: str, director_reason: str):
        """やなエントリ追加（TurnCard風 - Director情報付き）"""
        self._hide_placeholder()
        icon, badge_color, reason_style = self._get_director_badge_style(director_status)
        beat = self.turn_data.get(turn_num, {}).get('beat', '')

        with self.timeline_widget:
            # TurnCard風カード（rose-50背景）
            with ui.element('div').classes('w-full border rounded-lg p-3 bg-rose-50 border-rose-200'):
                # ヘッダー行（ターン番号、話者バッジ、Beatバッジ、Director判定、詳細ボタン）
                with ui.row().classes('w-full items-center justify-between text-sm'):
                    with ui.row().classes('items-center gap-2'):
                        ui.label(f'#{turn_num}').classes('font-mono text-slate-500')
                        ui.badge('やな', color='#f43f5e').classes('text-white text-xs font-bold px-2 py-1')
                        if beat:
                            ui.badge(beat, color='gray').props('outline').classes('text-xs')
                        if director_status:
                            ui.badge(f'{icon} {director_status}', color=badge_color).props('outline').classes('text-xs font-medium')
                    if turn_num > 0:
                        ui.button('詳細', on_click=lambda t=turn_num: self._show_detail(t)).props('flat dense size=sm').classes('text-xs')

                # 本文（テキスト左 + アイコン右）- TurnCard風配置
                with ui.row().classes('mt-3 items-start gap-4 w-full flex-nowrap'):
                    # テキスト（左側、flex-1）
                    with ui.element('div').classes('flex-1 p-3 bg-white/80 rounded-lg shadow-sm'):
                        ui.label(text).classes('text-[20px] leading-relaxed text-gray-800 whitespace-pre-wrap')
                    # アイコン（右側、200px固定）
                    ui.image(self.icon_yana).classes('w-[200px] h-[200px] rounded-lg object-cover shrink-0 border-2 border-white shadow-lg')

                # Director理由（常に表示）
                if director_reason:
                    with ui.element('div').classes(f'mt-2 p-2 rounded text-sm {reason_style}'):
                        status_label = '✓ Director判定:' if director_status == 'PASS' else ('🔄 再生成の理由:' if director_status == 'RETRY' else '⚠️ 問題点:')
                        ui.label(status_label).classes('font-medium text-xs mb-1')
                        ui.label(director_reason[:100] + ('...' if len(director_reason) > 100 else '')).classes('text-slate-600 text-xs')

        self._scroll_to_bottom()

    def _add_ayu_entry_with_director(self, text: str, turn_num: int, director_status: str, director_reason: str):
        """あゆエントリ追加（TurnCard風 - Director情報付き）"""
        self._hide_placeholder()
        icon, badge_color, reason_style = self._get_director_badge_style(director_status)
        beat = self.turn_data.get(turn_num, {}).get('beat', '')

        with self.timeline_widget:
            # TurnCard風カード（sky-50背景）
            with ui.element('div').classes('w-full border rounded-lg p-3 bg-sky-50 border-sky-200'):
                # ヘッダー行（ターン番号、話者バッジ、Beatバッジ、Director判定、詳細ボタン）
                with ui.row().classes('w-full items-center justify-between text-sm'):
                    with ui.row().classes('items-center gap-2'):
                        ui.label(f'#{turn_num}').classes('font-mono text-slate-500')
                        ui.badge('あゆ', color='#0ea5e9').classes('text-white text-xs font-bold px-2 py-1')
                        if beat:
                            ui.badge(beat, color='gray').props('outline').classes('text-xs')
                        if director_status:
                            ui.badge(f'{icon} {director_status}', color=badge_color).props('outline').classes('text-xs font-medium')
                    if turn_num > 0:
                        ui.button('詳細', on_click=lambda t=turn_num: self._show_detail(t)).props('flat dense size=sm').classes('text-xs')

                # 本文（テキスト左 + アイコン右）- TurnCard風配置
                with ui.row().classes('mt-3 items-start gap-4 w-full flex-nowrap'):
                    # テキスト（左側、flex-1）
                    with ui.element('div').classes('flex-1 p-3 bg-white/80 rounded-lg shadow-sm'):
                        ui.label(text).classes('text-[20px] leading-relaxed text-gray-800 whitespace-pre-wrap')
                    # アイコン（右側、200px固定）
                    ui.image(self.icon_ayu).classes('w-[200px] h-[200px] rounded-lg object-cover shrink-0 border-2 border-white shadow-lg')

                # Director理由（常に表示）
                if director_reason:
                    with ui.element('div').classes(f'mt-2 p-2 rounded text-sm {reason_style}'):
                        status_label = '✓ Director判定:' if director_status == 'PASS' else ('🔄 再生成の理由:' if director_status == 'RETRY' else '⚠️ 問題点:')
                        ui.label(status_label).classes('font-medium text-xs mb-1')
                        ui.label(director_reason[:100] + ('...' if len(director_reason) > 100 else '')).classes('text-slate-600 text-xs')

        self._scroll_to_bottom()

    def _show_detail(self, turn_num: int):
        """詳細モーダルを表示"""
        if turn_num not in self.turn_data:
            ui.notify(f'Turn {turn_num} data not found', type='warning')
            return

        data = self.turn_data[turn_num]
        self.detail_content.clear()

        with self.detail_content:
            # ヘッダー
            with ui.row().classes('w-full items-center justify-between'):
                ui.label(f'Turn #{turn_num} 詳細').classes('text-xl font-bold')
                ui.button('閉じる', on_click=self.detail_dialog.close).props('flat')

            ui.separator()

            # 話者情報
            speaker_name = 'やな' if data['speaker'] == 'A' else 'あゆ'
            speaker_color = 'pink' if data['speaker'] == 'A' else 'purple'
            with ui.row().classes('items-center gap-2'):
                ui.badge(speaker_name, color=speaker_color)
                ui.label(f'Frame {data["frame"]}').classes('text-gray-500')
                if data['beat']:
                    ui.badge(data['beat'], color='blue').props('outline')

            # 発言テキスト
            ui.label('発言内容').classes('font-bold mt-4')
            with ui.card().classes('w-full'):
                ui.label(data['text']).classes('text-lg')

            # Director判定
            ui.label('Director判定').classes('font-bold mt-4')
            icon, _, style = self._get_director_badge_style(data['director_status'])
            with ui.element('div').classes(f'p-4 rounded-lg {style}'):
                ui.label(f'{icon} {data["director_status"]}').classes('font-bold')
                if data['director_reason']:
                    ui.label('判定理由:').classes('font-medium mt-2')
                    ui.label(data['director_reason']).classes('text-sm')
                if data['director_guidance']:
                    ui.label('次ターンへの指示:').classes('font-medium mt-2')
                    ui.label(data['director_guidance']).classes('text-sm')

            # フレーム説明
            ui.label('フレーム説明').classes('font-bold mt-4')
            with ui.card().classes('w-full'):
                ui.label(data['frame_desc']).classes('text-sm text-gray-600')

        self.detail_dialog.open()

    def _add_warning_entry(self, text: str):
        """警告エントリ追加（カード形式）"""
        self._hide_placeholder()
        with self.timeline_widget:
            with ui.element('div').classes('w-full p-3 bg-amber-50 border border-amber-200 rounded-lg'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('warning').classes('text-amber-500')
                    ui.label('Warning').classes('font-bold text-amber-700')
                ui.label(text).classes('text-sm text-amber-600 mt-1')
        self._scroll_to_bottom()

    def _add_error_entry(self, text: str):
        """エラーエントリ追加（カード形式）"""
        self._hide_placeholder()
        with self.timeline_widget:
            with ui.element('div').classes('w-full p-3 bg-red-50 border border-red-200 rounded-lg'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('error').classes('text-red-500')
                    ui.label('Error').classes('font-bold text-red-700')
                ui.label(text).classes('text-sm text-red-600 mt-1')
        self._scroll_to_bottom()

    def _add_info_entry(self, text: str):
        """情報エントリ追加（カード形式）"""
        self._hide_placeholder()
        with self.timeline_widget:
            with ui.element('div').classes('w-full p-3 bg-gray-50 border border-gray-200 rounded-lg'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('info').classes('text-gray-500')
                    ui.label('Info').classes('font-bold text-gray-700')
                ui.label(text).classes('text-sm text-gray-600 mt-1')
        self._scroll_to_bottom()


def main():
    dashboard = DuoTalkDashboard()
    dashboard.create_ui()
    ui.run(title='duo-talk Dashboard', port=8080, reload=False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
