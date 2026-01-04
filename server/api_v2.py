#!/usr/bin/env python3
"""
DUO-TALK v2.1 API Extensions
DuoSignals, NoveltyGuard, SilenceController のリアルタイム状態を配信
"""

import sys
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, Generator

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Blueprint, jsonify, request, Response
from src.signals import DuoSignals, SignalEvent, EventType, DuoSignalsState
from src.novelty_guard import NoveltyGuard, LoopBreakStrategy
from src.silence_controller import SilenceController, SilenceType
from src.character import Character
from src.jetracer_client import JetRacerClient
from src.jetracer_provider import JetRacerProvider, DataMode
from src.sister_memory import get_sister_memory
from src.owner_intervention import get_intervention_manager, InterventionState

# Blueprint for v2.1 APIs
v2_api = Blueprint('v2_api', __name__, url_prefix='/api/v2')

# Global instances
_signals: Optional[DuoSignals] = None
_novelty_guard: Optional[NoveltyGuard] = None
_silence_controller: Optional[SilenceController] = None
_characters: Dict[str, Character] = {}
_jetracer_provider: Optional[JetRacerProvider] = None


def get_signals() -> DuoSignals:
    global _signals
    if _signals is None:
        DuoSignals.reset_instance()
        _signals = DuoSignals()
    return _signals


def get_novelty_guard() -> NoveltyGuard:
    global _novelty_guard
    if _novelty_guard is None:
        _novelty_guard = NoveltyGuard()
    return _novelty_guard


def get_silence_controller() -> SilenceController:
    global _silence_controller
    if _silence_controller is None:
        _silence_controller = SilenceController()
    return _silence_controller


def get_character(char_id: str) -> Character:
    global _characters
    if char_id not in _characters:
        _characters[char_id] = Character(char_id)
    return _characters[char_id]


# ==================== DuoSignals API ====================

@v2_api.route('/signals', methods=['GET'])
def get_signals_state():
    """現在のDuoSignals状態を取得"""
    signals = get_signals()
    state = signals.snapshot()

    return jsonify({
        "status": "ok",
        "state": {
            "jetracer_mode": state.jetracer_mode,
            "current_speed": state.current_speed,
            "steering_angle": state.steering_angle,
            "distance_sensors": state.distance_sensors,
            "scene_facts": state.scene_facts,
            "last_speaker": state.last_speaker,
            "turn_count": state.turn_count,
            "current_topic": state.current_topic,
            "topic_depth": state.topic_depth,
            "recent_topics": state.recent_topics[-5:],
            "recent_events": state.recent_events[-3:],
            "last_updated": state.last_updated.isoformat(),
            "is_stale": signals.is_stale()
        }
    })


@v2_api.route('/signals/update', methods=['POST'])
def update_signals():
    """DuoSignalsを更新（テスト/シミュレーション用）"""
    data = request.get_json()
    signals = get_signals()

    event_type_str = data.get('event_type', 'sensor')
    event_data = data.get('data', {})

    try:
        event_type = EventType(event_type_str)
        signals.update(SignalEvent(event_type=event_type, data=event_data))
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@v2_api.route('/signals/stream', methods=['GET'])
def stream_signals():
    """DuoSignals状態をSSEでストリーム"""
    def generate():
        signals = get_signals()
        last_update = None

        while True:
            state = signals.snapshot()
            current_update = state.last_updated

            # 更新があった場合のみ送信
            if last_update is None or current_update > last_update:
                event_data = {
                    "jetracer_mode": state.jetracer_mode,
                    "current_speed": state.current_speed,
                    "steering_angle": state.steering_angle,
                    "distance_sensors": state.distance_sensors,
                    "scene_facts": state.scene_facts,
                    "turn_count": state.turn_count,
                    "topic_depth": state.topic_depth,
                    "is_stale": signals.is_stale(),
                    "timestamp": current_update.isoformat()
                }
                yield f"event: signals\ndata: {json.dumps(event_data)}\n\n"
                last_update = current_update

            time.sleep(0.5)

    return Response(generate(), mimetype='text/event-stream',
                   headers={'Cache-Control': 'no-cache'})


# ==================== NoveltyGuard API ====================

@v2_api.route('/novelty/status', methods=['GET'])
def get_novelty_status():
    """NoveltyGuardの状態を取得"""
    guard = get_novelty_guard()
    stats = guard.get_stats()

    return jsonify({
        "status": "ok",
        "novelty_guard": stats
    })


@v2_api.route('/novelty/check', methods=['POST'])
def check_novelty():
    """テキストのループ検知をチェック"""
    data = request.get_json()
    text = data.get('text', '')

    guard = get_novelty_guard()
    result = guard.check_and_update(text)

    return jsonify({
        "status": "ok",
        "result": {
            "loop_detected": result.loop_detected,
            "stuck_nouns": result.stuck_nouns,
            "strategy": result.strategy.value if result.strategy else None,
            "topic_depth": result.topic_depth,
            "injection": result.injection
        }
    })


# ==================== SilenceController API ====================

@v2_api.route('/silence/check', methods=['GET'])
def check_silence():
    """現在の状態で沈黙すべきかチェック"""
    signals = get_signals()
    controller = get_silence_controller()
    state = signals.snapshot()

    silence = controller.should_silence(state)

    if silence:
        return jsonify({
            "status": "ok",
            "should_silence": True,
            "silence": {
                "type": silence.silence_type.value,
                "duration": silence.duration_seconds,
                "allow_short": silence.allow_short_utterance,
                "sfx": silence.suggested_sfx,
                "bgm_intensity": silence.suggested_bgm_intensity
            }
        })
    else:
        return jsonify({
            "status": "ok",
            "should_silence": False
        })


# ==================== Character v2 API ====================

@v2_api.route('/speak', methods=['POST'])
def speak_v2():
    """speak_v2を使った発話生成"""
    data = request.get_json()

    char_id = data.get('character', 'A')
    last_utterance = data.get('last_utterance', '')
    frame_description = data.get('frame_description', '')
    history = data.get('history', [])

    character = get_character(char_id)

    result = character.speak_v2(
        last_utterance=last_utterance,
        context={"history": history},
        frame_description=frame_description
    )

    return jsonify({
        "status": "ok",
        "result": result
    })


# ==================== JetRacer Integration ====================

@v2_api.route('/jetracer/connect', methods=['POST'])
def connect_jetracer():
    """JetRacerに接続"""
    global _jetracer_provider

    data = request.get_json()
    url = data.get('url', 'http://192.168.1.65:8000')
    mode = data.get('mode', 'sensor_only')

    try:
        client = JetRacerClient(url, timeout=5.0)
        status = client.get_status()

        if status:
            data_mode = DataMode(mode)
            _jetracer_provider = JetRacerProvider(client, data_mode)
            return jsonify({
                "status": "ok",
                "message": f"Connected to {url}",
                "mode": mode
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Connection failed"
            }), 503
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@v2_api.route('/jetracer/fetch', methods=['GET'])
def fetch_jetracer():
    """JetRacerからデータ取得してDuoSignalsに反映"""
    global _jetracer_provider

    if _jetracer_provider is None:
        return jsonify({
            "status": "error",
            "message": "Not connected to JetRacer"
        }), 400

    try:
        full_state = _jetracer_provider.fetch()

        if not full_state.valid or full_state.sensor is None:
            return jsonify({
                "status": "error",
                "message": "Failed to fetch sensor data"
            }), 503

        sensor = full_state.sensor
        signals = get_signals()

        # センサーイベント
        signals.update(SignalEvent(
            event_type=EventType.SENSOR,
            data={
                "speed": abs(sensor.throttle) * 3.0,
                "steering": sensor.steering * 45,
                "sensors": {
                    "distance": sensor.min_distance,
                    "temperature": sensor.temperature
                }
            }
        ))

        # VLM観測（VISIONモード時）
        if full_state.vision and full_state.vision.road_percentage > 0:
            signals.update(SignalEvent(
                event_type=EventType.VLM,
                data={
                    "facts": {
                        "road_percentage": f"{full_state.vision.road_percentage:.0f}%",
                        "inference_time": f"{full_state.vision.inference_time_ms:.0f}ms"
                    }
                }
            ))

        frame_desc = _jetracer_provider.to_frame_description(full_state)

        return jsonify({
            "status": "ok",
            "frame_description": frame_desc,
            "sensor": {
                "speed": sensor.throttle,
                "steering": sensor.steering,
                "distance": sensor.min_distance,
                "temperature": sensor.temperature,
                "mode": sensor.mode
            },
            "vision": {
                "road_percentage": full_state.vision.road_percentage if full_state.vision else 0,
                "inference_time": full_state.vision.inference_time_ms if full_state.vision else 0
            } if full_state.vision else None
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@v2_api.route('/jetracer/stream', methods=['GET'])
def stream_jetracer():
    """JetRacerデータをSSEでストリーム"""
    global _jetracer_provider

    if _jetracer_provider is None:
        return jsonify({
            "status": "error",
            "message": "Not connected to JetRacer"
        }), 400

    interval = float(request.args.get('interval', 1.0))

    def generate():
        signals = get_signals()

        while True:
            try:
                full_state = _jetracer_provider.fetch()

                if full_state.valid and full_state.sensor:
                    sensor = full_state.sensor

                    # DuoSignals更新
                    signals.update(SignalEvent(
                        event_type=EventType.SENSOR,
                        data={
                            "speed": abs(sensor.throttle) * 3.0,
                            "steering": sensor.steering * 45,
                            "sensors": {
                                "distance": sensor.min_distance,
                                "temperature": sensor.temperature
                            }
                        }
                    ))

                    event_data = {
                        "sensor": {
                            "speed": sensor.throttle,
                            "steering": sensor.steering,
                            "distance": sensor.min_distance,
                            "temperature": sensor.temperature,
                            "mode": sensor.mode
                        },
                        "frame_description": _jetracer_provider.to_frame_description(full_state),
                        "timestamp": datetime.now().isoformat()
                    }

                    if full_state.vision:
                        event_data["vision"] = {
                            "road_percentage": full_state.vision.road_percentage,
                            "inference_time": full_state.vision.inference_time_ms
                        }

                    yield f"event: jetracer\ndata: {json.dumps(event_data)}\n\n"
            except Exception as e:
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

            time.sleep(interval)

    return Response(generate(), mimetype='text/event-stream',
                   headers={'Cache-Control': 'no-cache'})


# ==================== Live Commentary ====================

@v2_api.route('/live/start', methods=['POST'])
def start_live_commentary():
    """ライブコメンタリーセッション開始"""
    data = request.get_json()

    # JetRacer接続確認
    jetracer_url = data.get('jetracer_url', 'http://192.168.1.65:8000')
    turns_per_frame = data.get('turns_per_frame', 4)
    interval = data.get('interval', 3.0)

    # セッションID生成
    session_id = f"live_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    return jsonify({
        "status": "ok",
        "session_id": session_id,
        "config": {
            "jetracer_url": jetracer_url,
            "turns_per_frame": turns_per_frame,
            "interval": interval
        }
    })


@v2_api.route('/live/dialogue', methods=['POST'])
def generate_live_dialogue():
    """1フレーム分の対話を生成"""
    data = request.get_json()

    frame_description = data.get('frame_description', '')
    history = data.get('history', [])
    turns = data.get('turns', 2)

    signals = get_signals()
    novelty_guard = get_novelty_guard()
    silence_controller = get_silence_controller()

    state = signals.snapshot()

    # 沈黙チェック
    silence = silence_controller.should_silence(state)
    if silence:
        return jsonify({
            "status": "ok",
            "type": "silence",
            "silence": {
                "type": silence.silence_type.value,
                "duration": silence.duration_seconds
            }
        })

    # 対話生成
    dialogue = []
    for turn in range(turns):
        char_id = "A" if turn % 2 == 0 else "B"
        character = get_character(char_id)

        last_utterance = dialogue[-1]["content"] if dialogue else (
            history[-1]["content"] if history else "(画面を見ている)"
        )

        result = character.speak_v2(
            last_utterance=last_utterance,
            context={"history": history + dialogue},
            frame_description=frame_description
        )

        if result["type"] == "speech":
            speaker_name = "やな" if char_id == "A" else "あゆ"
            dialogue.append({
                "speaker": speaker_name,
                "content": result["content"],
                "debug": result.get("debug", {})
            })

    return jsonify({
        "status": "ok",
        "type": "dialogue",
        "dialogue": dialogue
    })


# ==================== Sister Memory API ====================

@v2_api.route('/memory/search', methods=['GET'])
def memory_search():
    """関連する記憶を検索"""
    query = request.args.get('query', '')
    character = request.args.get('character', 'yana')
    n = int(request.args.get('n', 3))

    memory = get_sister_memory()
    results = memory.search(query, character, n)

    return jsonify({
        "status": "ok",
        "results": [{
            'event_id': r.event_id,
            'summary': r.summary,
            'perspective': r.perspective,
            'emotional_tag': r.emotional_tag,
            'relevance_score': r.relevance_score,
            'timestamp': r.timestamp
        } for r in results]
    })


@v2_api.route('/memory/stats', methods=['GET'])
def memory_stats():
    """記憶の統計情報を取得"""
    memory = get_sister_memory()
    stats = memory.get_stats()

    return jsonify({
        "status": "ok",
        "stats": {
            'total_memories': stats.total_memories,
            'buffer_size': stats.buffer_size,
            'emotional_tag_distribution': stats.emotional_tag_distribution,
            'oldest_memory': stats.oldest_memory,
            'newest_memory': stats.newest_memory
        }
    })


@v2_api.route('/memory/buffer', methods=['POST'])
def memory_buffer():
    """記憶をバッファに追加"""
    data = request.get_json()
    memory = get_sister_memory()

    event_id = memory.buffer_event(
        event_summary=data.get('event_summary', ''),
        yana_perspective=data.get('yana_perspective', ''),
        ayu_perspective=data.get('ayu_perspective', ''),
        emotional_tag=data.get('emotional_tag', 'routine'),
        context_tags=data.get('context_tags', []),
        run_id=data.get('run_id'),
        turn_number=data.get('turn_number')
    )

    return jsonify({
        "status": "ok",
        "event_id": event_id,
        "buffer_size": memory.get_buffer_size()
    })


@v2_api.route('/memory/flush', methods=['POST'])
def memory_flush():
    """バッファの記憶をDBに書き込み"""
    data = request.get_json() or {}
    validate = data.get('validate', True)

    memory = get_sister_memory()
    result = memory.flush_buffer(validate)

    return jsonify({
        "status": "ok",
        "result": {
            'total': result.total,
            'written': result.written,
            'skipped': result.skipped,
            'errors': result.errors,
            'skipped_reasons': result.skipped_reasons
        }
    })


@v2_api.route('/memory/buffer/size', methods=['GET'])
def memory_buffer_size():
    """現在のバッファサイズを取得"""
    memory = get_sister_memory()
    return jsonify({
        "status": "ok",
        "buffer_size": memory.get_buffer_size()
    })


@v2_api.route('/memory/buffer', methods=['DELETE'])
def memory_buffer_clear():
    """バッファをクリア"""
    memory = get_sister_memory()
    memory.clear_buffer()
    return jsonify({
        "status": "ok",
        "message": "Buffer cleared"
    })


# ==================== Owner Intervention API ====================

@v2_api.route('/intervention/status', methods=['GET'])
def intervention_status():
    """現在の介入状態を取得"""
    manager = get_intervention_manager()
    status = manager.get_status()

    return jsonify({
        "status": "ok",
        "intervention": status
    })


@v2_api.route('/intervention/pause', methods=['POST'])
def intervention_pause():
    """対話を一時停止"""
    data = request.get_json() or {}
    run_id = data.get('run_id', 'default')

    manager = get_intervention_manager()

    if manager.get_state() != InterventionState.RUNNING:
        return jsonify({
            "status": "error",
            "message": "Already paused or processing"
        }), 400

    session = manager.pause(run_id)

    return jsonify({
        "status": "ok",
        "session": {
            "session_id": session.session_id,
            "run_id": session.run_id,
            "state": session.state.value,
            "created_at": session.created_at
        }
    })


@v2_api.route('/intervention/resume', methods=['POST'])
def intervention_resume():
    """対話を再開"""
    manager = get_intervention_manager()

    if manager.get_state() == InterventionState.RUNNING:
        return jsonify({
            "status": "ok",
            "message": "Already running"
        })

    success = manager.resume()

    if success:
        return jsonify({
            "status": "ok",
            "message": "Resumed"
        })
    else:
        return jsonify({
            "status": "error",
            "message": "Cannot resume from current state"
        }), 400


@v2_api.route('/intervention/send', methods=['POST'])
def intervention_send():
    """オーナーメッセージを送信"""
    data = request.get_json()

    if not data or 'message' not in data:
        return jsonify({
            "status": "error",
            "message": "Message is required"
        }), 400

    message = data['message']
    message_type = data.get('type', 'instruction')

    manager = get_intervention_manager()
    result = manager.process_owner_message(message, message_type)

    response = {
        "status": "ok" if result.success else "error",
        "result": {
            "success": result.success,
            "state": result.state.value,
            "needs_clarification": result.needs_clarification,
            "next_action": result.next_action,
            "error": result.error
        }
    }

    if result.query_back:
        response["result"]["query_back"] = {
            "from_character": result.query_back.from_character,
            "question": result.query_back.question,
            "context": result.query_back.context,
            "options": result.query_back.options
        }

    if result.interpretation:
        response["result"]["interpretation"] = {
            "target_character": result.interpretation.target_character,
            "instruction_type": result.interpretation.instruction_type,
            "instruction_content": result.interpretation.instruction_content,
            "confidence": result.interpretation.confidence
        }

    return jsonify(response)


@v2_api.route('/intervention/answer', methods=['POST'])
def intervention_answer():
    """逆質問に回答"""
    data = request.get_json()

    if not data or 'answer' not in data:
        return jsonify({
            "status": "error",
            "message": "Answer is required"
        }), 400

    answer = data['answer']

    manager = get_intervention_manager()
    result = manager.answer_query_back(answer)

    return jsonify({
        "status": "ok" if result.success else "error",
        "result": {
            "success": result.success,
            "state": result.state.value,
            "next_action": result.next_action,
            "error": result.error
        }
    })


@v2_api.route('/intervention/log', methods=['GET'])
def intervention_log():
    """介入ログを取得"""
    run_id = request.args.get('run_id')

    manager = get_intervention_manager()
    log = manager.get_log(run_id)

    return jsonify({
        "status": "ok",
        "log": log
    })


@v2_api.route('/intervention/instruction', methods=['GET'])
def intervention_instruction():
    """適用待ちの指示を取得（対話生成時に使用）"""
    manager = get_intervention_manager()

    instruction = manager.get_pending_instruction()
    target = manager.get_target_character()

    return jsonify({
        "status": "ok",
        "instruction": instruction,
        "target_character": target
    })


@v2_api.route('/intervention/instruction/clear', methods=['POST'])
def intervention_instruction_clear():
    """適用済みの指示をクリア"""
    manager = get_intervention_manager()
    manager.clear_pending_instruction()

    return jsonify({
        "status": "ok",
        "message": "Instruction cleared"
    })
