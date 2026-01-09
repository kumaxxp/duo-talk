"""
duo-talk 統一API Blueprint

UnifiedPipeline を使用した統一エンドポイント。
既存の /api/run/* と /api/v2/* を将来的に置き換える。

エンドポイント:
- POST /api/unified/run/start - 対話実行開始（SSEストリーム）
- POST /api/unified/run/start-sync - 対話実行（同期、結果を一括返却）
- GET /api/unified/run/status - 実行状態取得
- POST /api/unified/run/interrupt - 割り込み入力
- POST /api/unified/run/stop - 実行停止
- GET /api/unified/health - ヘルスチェック
"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Blueprint, jsonify, request, Response
from typing import Optional, Dict, Any, List
import json
import threading
import queue
from datetime import datetime

from src.unified_pipeline import UnifiedPipeline, DialogueResult
from src.input_source import InputBundle, InputSource, SourceType

# JetRacerClientは動的インポート（接続失敗時のエラー回避）
try:
    from src.jetracer_client import JetRacerClient
    JETRACER_AVAILABLE = True
except ImportError:
    JETRACER_AVAILABLE = False
    JetRacerClient = None


unified_api = Blueprint('unified_api', __name__, url_prefix='/api/unified')

# グローバル状態
_pipeline: Optional[UnifiedPipeline] = None
_current_run: Optional[Dict[str, Any]] = None
_interrupt_queue: queue.Queue = queue.Queue()
_stop_requested: bool = False
_lock = threading.Lock()


def _get_pipeline(jetracer_url: Optional[str] = None) -> UnifiedPipeline:
    """パイプラインインスタンスを取得（シングルトン）"""
    global _pipeline

    with _lock:
        if _pipeline is None:
            jetracer_client = None
            if jetracer_url and JETRACER_AVAILABLE and JetRacerClient:
                try:
                    jetracer_client = JetRacerClient(base_url=jetracer_url)
                    print(f"[unified_api] JetRacer connected: {jetracer_url}")
                except Exception as e:
                    print(f"[unified_api] JetRacer connection failed: {e}")

            _pipeline = UnifiedPipeline(
                jetracer_client=jetracer_client,
                enable_fact_check=False,  # Disabled to avoid timeout from DuckDuckGo search
            )
            print("[unified_api] UnifiedPipeline initialized")

    return _pipeline


def _build_input_bundle(data: Dict[str, Any]) -> InputBundle:
    """リクエストデータからInputBundleを構築"""
    sources: List[InputSource] = []

    # テキスト入力
    text = data.get('text') or data.get('topic') or data.get('scene_description')
    if text:
        sources.append(InputSource(
            source_type=SourceType.TEXT,
            content=text
        ))

    # 画像ファイル
    image_path = data.get('imagePath') or data.get('image_path')
    if image_path:
        sources.append(InputSource(
            source_type=SourceType.IMAGE_FILE,
            content=image_path
        ))

    # 画像URL
    image_url = data.get('imageUrl') or data.get('image_url')
    if image_url:
        sources.append(InputSource(
            source_type=SourceType.IMAGE_URL,
            content=image_url
        ))

    # JetRacer カメラ
    if data.get('useJetRacerCam') or data.get('jetracer_cam'):
        cam_id = data.get('jetracerCamId', data.get('jetracer_cam_id', 0))
        source_type = SourceType.JETRACER_CAM0 if cam_id == 0 else SourceType.JETRACER_CAM1
        sources.append(InputSource(source_type=source_type))

    # JetRacer センサー
    if data.get('useJetRacerSensor') or data.get('jetracer_sensor'):
        sources.append(InputSource(source_type=SourceType.JETRACER_SENSOR))

    # is_interrupt フラグ
    is_interrupt = data.get('is_interrupt', False)

    return InputBundle(sources=sources, is_interrupt=is_interrupt)


@unified_api.route('/run/start', methods=['POST'])
def start_run_sse():
    """
    対話実行開始（SSEストリーム）

    Body:
        text: str - テキスト入力（topic, scene_description でも可）
        imagePath: str - 画像ファイルパス（optional）
        imageUrl: str - 画像URL（optional）
        useJetRacerCam: bool - JetRacerカメラ使用（optional）
        jetracerCamId: int - カメラID 0 or 1（default: 0）
        useJetRacerSensor: bool - JetRacerセンサー使用（optional）
        jetracerUrl: str - JetRacer URL（optional）
        maxTurns: int - 最大ターン数（default: 8）

    Returns:
        SSE stream with events:
        - narration_start: 開始
        - speak: 発話
        - interrupt: 割り込み
        - narration_complete: 完了
        - error: エラー
    """
    global _current_run, _stop_requested, _interrupt_queue

    data = request.get_json() or {}

    # 入力バンドル構築
    bundle = _build_input_bundle(data)
    if bundle.is_empty:
        return jsonify({"error": "At least one input source required"}), 400

    # パラメータ
    max_turns = data.get('maxTurns', data.get('max_turns', 8))
    jetracer_url = data.get('jetracerUrl', data.get('jetracer_url'))

    # パイプライン取得
    pipeline = _get_pipeline(jetracer_url)

    # 状態リセット
    with _lock:
        _stop_requested = False
        _interrupt_queue = queue.Queue()

    def generate():
        global _current_run, _stop_requested

        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        with _lock:
            _current_run = {"run_id": run_id, "status": "running"}

        try:
            # イベント収集リスト
            collected_events: List[tuple] = []

            # 割り込みコールバック
            def interrupt_callback() -> Optional[InputBundle]:
                global _stop_requested
                if _stop_requested:
                    return None
                try:
                    interrupt_data = _interrupt_queue.get_nowait()
                    return _build_input_bundle(interrupt_data)
                except queue.Empty:
                    return None

            # イベントコールバック（収集用）
            def event_callback(event_type: str, event_data: dict):
                collected_events.append((event_type, event_data))

            # 実行
            result = pipeline.run(
                initial_input=bundle,
                max_turns=max_turns,
                run_id=run_id,
                interrupt_callback=interrupt_callback,
                event_callback=event_callback,
            )

            # 収集したイベントを送信
            for event_type, event_data in collected_events:
                if _stop_requested:
                    break
                yield f"event: {event_type}\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"

            # 完了イベント
            with _lock:
                if _current_run:
                    _current_run["status"] = result.status

            complete_data = {
                'status': result.status,
                'run_id': run_id,
                'turns': len(result.dialogue),
            }
            if result.error:
                complete_data['error'] = result.error

            yield f"event: complete\ndata: {json.dumps(complete_data, ensure_ascii=False)}\n\n"

        except Exception as e:
            with _lock:
                if _current_run:
                    _current_run["status"] = "error"
                    _current_run["error"] = str(e)

            yield f"event: error\ndata: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

        finally:
            with _lock:
                _current_run = None

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
            'Access-Control-Allow-Origin': '*',
        }
    )


@unified_api.route('/run/start-sync', methods=['POST'])
def start_run_sync():
    """
    対話実行（同期、結果を一括返却）

    Body: start_run_sse と同じ

    Returns:
        {
            "status": "success" | "error",
            "run_id": str,
            "dialogue": [
                {"turn_number": 0, "speaker": "A", "speaker_name": "やな", "text": "..."},
                ...
            ],
            "error": str | null
        }
    """
    global _current_run

    data = request.get_json() or {}

    # 入力バンドル構築
    bundle = _build_input_bundle(data)
    if bundle.is_empty:
        return jsonify({"error": "At least one input source required"}), 400

    # パラメータ
    max_turns = data.get('maxTurns', data.get('max_turns', 8))
    jetracer_url = data.get('jetracerUrl', data.get('jetracer_url'))

    # パイプライン取得・実行
    pipeline = _get_pipeline(jetracer_url)

    try:
        result = pipeline.run(
            initial_input=bundle,
            max_turns=max_turns,
        )

        response_data = {
            "status": result.status,
            "run_id": result.run_id,
            "dialogue": [turn.to_dict() for turn in result.dialogue],
            "error": result.error,
        }

        return jsonify(response_data)

    except Exception as e:
        return jsonify({
            "status": "error",
            "run_id": None,
            "dialogue": [],
            "error": str(e),
        }), 500


@unified_api.route('/run/status', methods=['GET'])
def get_run_status():
    """
    実行状態取得

    Returns:
        {
            "running": bool,
            "run_id": str | null,
            "status": str | null
        }
    """
    global _current_run

    with _lock:
        if _current_run:
            return jsonify({
                "running": True,
                "run_id": _current_run.get("run_id"),
                "status": _current_run.get("status"),
            })
        else:
            return jsonify({
                "running": False,
                "run_id": None,
                "status": None,
            })


@unified_api.route('/run/interrupt', methods=['POST'])
def interrupt_run():
    """
    実行中の対話に割り込み入力を送信

    Body:
        text: str - 割り込みテキスト
        imagePath: str - 画像パス（optional）

    Returns:
        {"success": bool, "message": str}
    """
    global _current_run, _interrupt_queue

    with _lock:
        if not _current_run:
            return jsonify({"success": False, "message": "No run in progress"}), 400

    data = request.get_json() or {}
    if not data.get('text') and not data.get('imagePath'):
        return jsonify({"success": False, "message": "text or imagePath required"}), 400

    # 割り込みデータをキューに追加
    data['is_interrupt'] = True
    _interrupt_queue.put(data)

    with _lock:
        run_id = _current_run.get('run_id') if _current_run else 'unknown'

    return jsonify({
        "success": True,
        "message": f"Interrupt queued for run {run_id}",
    })


@unified_api.route('/run/stop', methods=['POST'])
def stop_run():
    """
    実行中の対話を停止

    Returns:
        {"success": bool, "message": str}
    """
    global _current_run, _stop_requested

    with _lock:
        if not _current_run:
            return jsonify({"success": False, "message": "No run in progress"}), 400

        _stop_requested = True
        run_id = _current_run.get('run_id')

    return jsonify({
        "success": True,
        "message": f"Stop requested for run {run_id}",
    })


@unified_api.route('/health', methods=['GET'])
def health_check():
    """ヘルスチェック"""
    global _pipeline, _current_run

    with _lock:
        return jsonify({
            "status": "ok",
            "pipeline_initialized": _pipeline is not None,
            "current_run": _current_run.get("run_id") if _current_run else None,
            "jetracer_available": JETRACER_AVAILABLE,
        })


# CORS対応のOPTIONSハンドラ
@unified_api.route('/run/start', methods=['OPTIONS'])
@unified_api.route('/run/start-sync', methods=['OPTIONS'])
@unified_api.route('/run/interrupt', methods=['OPTIONS'])
@unified_api.route('/run/stop', methods=['OPTIONS'])
def options_handler():
    """CORS preflight対応"""
    response = jsonify({})
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


# Blueprintを登録するためのヘルパー関数
def register_unified_api(app):
    """FlaskアプリにUnified APIを登録"""
    app.register_blueprint(unified_api)
    print("[unified_api] Blueprint registered at /api/unified")
