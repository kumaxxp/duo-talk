#!/usr/bin/env python3
"""
DUO-TALK Backend API Server

Provides REST API endpoints for the React GUI frontend.
Enables real-time monitoring of narration runs via SSE (Server-Sent Events).
"""

import sys
import json
import os
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, jsonify, request, Response, send_from_directory
from flask_cors import CORS
import logging

from src.config import config
from src.logger import get_logger
from src.feedback_analyzer import FeedbackAnalyzer
from src.vision_config import (
    get_vision_config_manager,
    VisionConfig,
    VisionMode,
    VLMType,
    SegmentationModel,
)
from scripts.run_narration import NarrationPipeline

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for React frontend

# Global state
pipeline = None
current_run_id = None


# ==================== RUN MANAGEMENT ====================

@app.route('/api/run/list', methods=['GET'])
def list_runs():
    """
    Get list of all narration runs.

    Returns:
        JSON: [{"run_id": "...", "topic": "...", "timestamp": "..."}]
    """
    try:
        runs_file = config.log_dir / "commentary_runs.jsonl"
        runs = []
        run_ids = {}

        if runs_file.exists():
            with open(runs_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        event = json.loads(line)
                        run_id = event.get('run_id')
                        if not run_id:
                            continue

                        # narration_start イベントからtopicを取得
                        if event.get('event') == 'narration_start':
                            if run_id not in run_ids:
                                run_ids[run_id] = {
                                    'run_id': run_id,
                                    'topic': event.get('topic'),
                                    'timestamp': event.get('timestamp'),
                                    'status': 'running'
                                }
                            else:
                                # topicを更新（narration_startが後から来た場合）
                                run_ids[run_id]['topic'] = event.get('topic') or run_ids[run_id].get('topic')

                        # narration_complete イベントでステータスを更新
                        elif event.get('event') == 'narration_complete':
                            if run_id not in run_ids:
                                run_ids[run_id] = {
                                    'run_id': run_id,
                                    'topic': event.get('topic') or event.get('scene'),
                                    'timestamp': event.get('timestamp'),
                                    'status': event.get('status', 'completed')
                                }
                            else:
                                run_ids[run_id]['status'] = event.get('status', 'completed')

                    except json.JSONDecodeError:
                        continue

            # Return most recent first
            runs = sorted(run_ids.values(),
                         key=lambda x: x.get('timestamp') or '',
                         reverse=True)

        return jsonify(runs)
    except Exception as e:
        logger.error(f"Error listing runs: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/run/events', methods=['GET'])
def get_run_events():
    """
    Get all events for a specific run.

    Query params:
        - run_id: The run ID to fetch events for

    Returns:
        JSON: [{"event": "...", "turn": ..., ...}]
    """
    try:
        run_id = request.args.get('run_id')
        if not run_id:
            return jsonify({"error": "run_id required"}), 400

        events = []
        runs_file = config.log_dir / "commentary_runs.jsonl"

        if runs_file.exists():
            with open(runs_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        event = json.loads(line)
                        if event.get('run_id') == run_id:
                            events.append(event)
                    except json.JSONDecodeError:
                        continue

        return jsonify(events)
    except Exception as e:
        logger.error(f"Error getting run events: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/run/stream', methods=['GET'])
def stream_run_events():
    """
    Server-Sent Events (SSE) stream for live run monitoring.

    Query params:
        - run_id: The run ID to stream events for

    Yields:
        SSE events with live narration and evaluation data
    """
    run_id = request.args.get('run_id')
    if not run_id:
        return jsonify({"error": "run_id required"}), 400

    def event_generator():
        """Generate SSE events from the run log file"""
        import time

        runs_file = config.log_dir / "commentary_runs.jsonl"
        last_pos = 0
        heartbeat_counter = 0
        run_complete = False
        timeout_counter = 0
        max_timeout = 120  # 60 seconds max wait after no new events

        # Send initial connection message
        yield f"event: connected\n"
        yield f"data: {{\"run_id\": \"{run_id}\", \"status\": \"connected\"}}\n\n"

        while not run_complete and timeout_counter < max_timeout:
            events_found = False
            try:
                if runs_file.exists():
                    with open(runs_file, 'r', encoding='utf-8') as f:
                        f.seek(last_pos)
                        for line in f:
                            try:
                                event = json.loads(line)
                                if event.get('run_id') == run_id:
                                    events_found = True
                                    # Format as SSE
                                    event_type = event.get('event', 'unknown')
                                    yield f"event: {event_type}\n"
                                    yield f"data: {json.dumps(event)}\n\n"

                                    # Check if run is complete
                                    if event_type == 'narration_complete':
                                        run_complete = True
                            except json.JSONDecodeError:
                                pass
                        last_pos = f.tell()
            except Exception as e:
                logger.error(f"Error in SSE stream: {e}")

            # Reset timeout if events were found, otherwise increment
            if events_found:
                timeout_counter = 0
            else:
                timeout_counter += 1

            # Send heartbeat every 10 iterations (5 seconds)
            heartbeat_counter += 1
            if heartbeat_counter >= 10:
                yield f": heartbeat\n\n"
                heartbeat_counter = 0

            # Small delay to prevent busy waiting
            time.sleep(0.5)

    return Response(event_generator(), mimetype='text/event-stream',
                   headers={'Cache-Control': 'no-cache'})


# ==================== NARRATION CONTROL ====================

@app.route('/api/narration/start', methods=['POST'])
def start_narration():
    """
    Start a new narration run.

    Body (JSON):
        - image_path: Path to image to analyze
        - scene_description: Description of the scene

    Returns:
        JSON: {"run_id": "...", "status": "running"}
    """
    global current_run_id, pipeline

    try:
        data = request.get_json()
        image_path = data.get('image_path')
        scene_description = data.get('scene_description')

        if not image_path:
            return jsonify({"error": "image_path required"}), 400

        # Generate run ID
        from datetime import datetime
        current_run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Initialize pipeline if needed
        if pipeline is None:
            pipeline = NarrationPipeline()

        # Process image in background (in production, use task queue)
        logger.info(f"Starting narration run: {current_run_id}")
        result = pipeline.process_image(image_path, scene_description)

        return jsonify({
            "run_id": current_run_id,
            "status": "completed",
            "result": result
        })

    except Exception as e:
        logger.error(f"Error starting narration: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/run/start', methods=['POST'])
def run_start():
    """
    Start a new narration run with optional image analysis.

    Body (JSON):
        - topic: Narration topic/scene description (optional if imagePath provided)
        - imagePath: Path to uploaded image for vision analysis (optional)
        - model: LLM model to use (e.g., "gemma3:12b")
        - maxTurns: Maximum number of turns (default: 8)
        - seed: Random seed for reproducibility
        - noRag: Boolean, whether to disable RAG (default: false)

    Returns:
        JSON: {"run_id": "...", "topic": "...", "hasImage": bool}
    """
    from datetime import datetime
    import json as json_module
    import threading

    try:
        data = request.get_json()
        topic = data.get('topic', '')
        image_path = data.get('imagePath')
        model = data.get('model', 'qwen2.5:7b-instruct-q4_K_M')
        max_turns = data.get('maxTurns', 8)
        seed = data.get('seed')
        no_rag = data.get('noRag', False)

        # Either topic or image is required
        if not topic and not image_path:
            return jsonify({"error": "topic or imagePath required"}), 400

        # Generate run ID
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Create run metadata event
        run_event = {
            "event": "narration_start",
            "run_id": run_id,
            "topic": topic or "(画像から生成)",
            "imagePath": image_path,
            "model": model,
            "maxTurns": max_turns,
            "seed": seed,
            "noRag": no_rag,
            "timestamp": datetime.now().isoformat()
        }

        # Write run start event to log
        runs_file = config.log_dir / "commentary_runs.jsonl"
        with open(runs_file, 'a', encoding='utf-8') as f:
            f.write(json_module.dumps(run_event, ensure_ascii=False) + '\n')

        has_image = bool(image_path)
        logger.info(f"Run started: {run_id} - Topic: {topic or '(from image)'} - Image: {has_image}")

        # Start narration pipeline in background thread
        def run_pipeline():
            try:
                logger.info(f"Starting pipeline for {run_id}")

                # Initialize pipeline
                pipeline = NarrationPipeline()

                # Determine if we should use vision analysis
                skip_vision = not has_image

                if has_image:
                    logger.info(f"Processing with image: {image_path}")
                    # Process with image - vision analysis will extract scene description
                    result = pipeline.process_image(
                        image_path=image_path,
                        scene_description=topic if topic else None,
                        max_iterations=max_turns,
                        run_id=run_id,
                        skip_vision=False,
                    )
                else:
                    logger.info(f"Processing with topic only: {topic}")
                    # Process with topic only (no vision analysis)
                    result = pipeline.process_image(
                        image_path=None,
                        scene_description=topic,
                        max_iterations=max_turns,
                        run_id=run_id,
                        skip_vision=True,
                    )

                # Log completion
                if result.get('status') == 'success':
                    completion_event = {
                        "event": "narration_complete",
                        "run_id": run_id,
                        "topic": topic or "(画像から生成)",
                        "status": "success",
                        "timestamp": datetime.now().isoformat()
                    }
                    with open(runs_file, 'a', encoding='utf-8') as f:
                        f.write(json_module.dumps(completion_event, ensure_ascii=False) + '\n')
                    logger.info(f"Pipeline completed for {run_id}")
                else:
                    logger.warning(f"Pipeline did not succeed for {run_id}: {result.get('status')}")

            except Exception as e:
                logger.error(f"Error in pipeline for {run_id}: {e}")
                import traceback
                traceback.print_exc()

        # Start pipeline in background thread
        thread = threading.Thread(target=run_pipeline, daemon=True)
        thread.start()

        # Return success immediately
        return jsonify({
            "run_id": run_id,
            "topic": topic or "(画像から生成)",
            "hasImage": has_image,
            "status": "queued"
        })

    except Exception as e:
        logger.error(f"Error in /api/run/start: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/run/style', methods=['GET'])
def get_run_style():
    """
    Get character style adherence metrics for a run.

    Query params:
        - run_id: The run ID to get style metrics for

    Returns:
        JSON: {"style_ok_rate": 0.85, "details": {...}}
    """
    try:
        run_id = request.args.get('run_id')
        if not run_id:
            return jsonify({"error": "run_id required"}), 400

        # For now, return placeholder values
        # In production, calculate from actual character style evaluation
        return jsonify({
            "style_ok_rate": 0.92,
            "character_a_consistency": 0.90,
            "character_b_consistency": 0.94,
            "language_purity": 0.91,
            "details": {
                "character_a": "やな style mostly consistent",
                "character_b": "あゆ style mostly consistent"
            }
        })
    except Exception as e:
        logger.error(f"Error getting run style: {e}")
        return jsonify({"error": str(e)}), 500


# ==================== IMAGE UPLOAD ====================

@app.route('/api/image/upload', methods=['POST'])
def upload_image():
    """
    Upload an image for vision analysis.

    Body (multipart/form-data):
        - image: Image file

    Returns:
        JSON: {"path": "/path/to/uploaded/image", "filename": "..."}
    """
    import uuid
    from werkzeug.utils import secure_filename

    try:
        if 'image' not in request.files:
            return jsonify({"error": "No image file provided"}), 400

        file = request.files['image']
        if file.filename == '':
            return jsonify({"error": "No selected file"}), 400

        # Check if it's an image
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'}
        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if ext not in allowed_extensions:
            return jsonify({"error": f"Invalid file type: {ext}. Allowed: {allowed_extensions}"}), 400

        # Create upload directory
        upload_dir = config.log_dir / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique filename
        safe_filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4().hex[:8]}_{safe_filename}"
        file_path = upload_dir / unique_filename

        # Save file
        file.save(str(file_path))
        logger.info(f"Image uploaded: {file_path}")

        return jsonify({
            "path": str(file_path),
            "filename": unique_filename,
            "size": file_path.stat().st_size
        })

    except Exception as e:
        logger.error(f"Error uploading image: {e}")
        return jsonify({"error": str(e)}), 500


# ==================== RAG & FEEDBACK ====================

@app.route('/api/rag/score', methods=['GET'])
def get_rag_score():
    """
    Get RAG (Retrieval-Augmented Generation) quality scores.

    Returns:
        JSON: {"f1": 0.95, "citation_rate": 0.92}
    """
    try:
        # For now, return placeholder values
        # In production, calculate from actual RAG evaluation
        return jsonify({
            "f1": 0.92,
            "citation_rate": 0.88
        })
    except Exception as e:
        logger.error(f"Error getting RAG score: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/feedback/trends', methods=['GET'])
def get_feedback_trends():
    """
    Get feedback trend analysis.

    Returns:
        JSON: {"trends": {...}, "by_character": {...}}
    """
    try:
        trends = FeedbackAnalyzer.analyze_trends()
        by_char = FeedbackAnalyzer.analyze_by_character()

        return jsonify({
            "trends": trends,
            "by_character": by_char
        })
    except Exception as e:
        logger.error(f"Error getting feedback trends: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/feedback/record', methods=['POST'])
def record_feedback():
    """
    Record user feedback for a narration turn.

    Body (JSON):
        - run_id: The run ID
        - turn_num: The turn number
        - speaker: "A" or "B"
        - issue_type: Type of issue
        - description: Issue description
        - suggested_fix: Optional suggestion

    Returns:
        JSON: {"status": "recorded"}
    """
    try:
        data = request.get_json()

        FeedbackAnalyzer.record_feedback(
            run_id=data.get('run_id'),
            turn_num=data.get('turn_num'),
            speaker=data.get('speaker'),
            issue_type=data.get('issue_type'),
            description=data.get('description'),
            suggested_fix=data.get('suggested_fix')
        )

        return jsonify({"status": "recorded"})
    except Exception as e:
        logger.error(f"Error recording feedback: {e}")
        return jsonify({"error": str(e)}), 500


# ==================== SYSTEM STATUS ====================

@app.route('/api/system/status', methods=['GET'])
def system_status():
    """
    Get system status and configuration.

    Returns:
        JSON: {"status": "running", "components": {...}}
    """
    try:
        return jsonify({
            "status": "running",
            "components": {
                "vision": True,
                "character_a": True,
                "character_b": True,
                "director": True,
                "rag": True,
                "logger": True,
                "hitl": True
            },
            "config": {
                "log_dir": str(config.log_dir),
                "rag_data_dir": str(config.rag_data_dir),
                "openai_base_url": config.openai_base_url
            }
        })
    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        return jsonify({"error": str(e)}), 500


# ==================== VISION SETTINGS ====================

@app.route('/api/vision/config', methods=['GET'])
def get_vision_config():
    """
    Get current vision processing configuration.

    Returns:
        JSON: Vision configuration object
    """
    try:
        manager = get_vision_config_manager()
        config = manager.get_current()
        return jsonify({
            "status": "ok",
            "config": config.to_dict()
        })
    except Exception as e:
        logger.error(f"Error getting vision config: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/vision/config', methods=['POST'])
def save_vision_config():
    """
    Save vision processing configuration.

    Body (JSON):
        Vision configuration fields

    Returns:
        JSON: {"status": "ok", "config": {...}}
    """
    try:
        data = request.get_json()
        manager = get_vision_config_manager()

        # Create config from data
        new_config = VisionConfig.from_dict(data)

        # Save configuration
        success = manager.save(new_config)
        if success:
            return jsonify({
                "status": "ok",
                "config": new_config.to_dict()
            })
        else:
            return jsonify({"error": "Failed to save configuration"}), 500
    except Exception as e:
        logger.error(f"Error saving vision config: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/vision/presets', methods=['GET'])
def get_vision_presets():
    """
    Get available vision configuration presets.

    Returns:
        JSON: List of preset configurations
    """
    try:
        manager = get_vision_config_manager()
        presets = manager.get_presets()
        return jsonify({
            "status": "ok",
            "presets": presets
        })
    except Exception as e:
        logger.error(f"Error getting vision presets: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/vision/presets/apply', methods=['POST'])
def apply_vision_preset():
    """
    Apply a vision configuration preset.

    Body (JSON):
        - preset_name: Name of the preset to apply

    Returns:
        JSON: {"status": "ok", "config": {...}}
    """
    try:
        data = request.get_json()
        preset_name = data.get('preset_name')

        if not preset_name:
            return jsonify({"error": "preset_name required"}), 400

        manager = get_vision_config_manager()
        new_config = manager.apply_preset(preset_name)

        if new_config:
            return jsonify({
                "status": "ok",
                "config": new_config.to_dict()
            })
        else:
            return jsonify({"error": f"Preset '{preset_name}' not found"}), 404
    except Exception as e:
        logger.error(f"Error applying vision preset: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/vision/models', methods=['GET'])
def get_available_models():
    """
    Get available VLM and segmentation model options.

    Returns:
        JSON: {"vlm_types": [...], "segmentation_models": [...], "modes": [...]}
    """
    try:
        manager = get_vision_config_manager()
        models = manager.get_available_models()
        return jsonify({
            "status": "ok",
            "models": models
        })
    except Exception as e:
        logger.error(f"Error getting available models: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/vision/test', methods=['POST'])
def test_vision_config():
    """
    Test vision configuration with a sample image.

    Body (JSON):
        - image_path: Path to test image
        - config: Optional config override to test

    Returns:
        JSON: Vision analysis result
    """
    try:
        from src.vision_processor import VisionProcessor

        data = request.get_json()
        image_path = data.get('image_path')

        if not image_path:
            return jsonify({"error": "image_path required"}), 400

        # Use provided config or current config
        config_data = data.get('config')
        if config_data:
            test_config = VisionConfig.from_dict(config_data)
        else:
            test_config = get_vision_config_manager().get_current()

        # Create processor with test config
        processor = VisionProcessor(config=test_config)

        # Run analysis
        result = processor.analyze_image(image_path)

        return jsonify({
            "status": "ok",
            "result": result
        })
    except Exception as e:
        logger.error(f"Error testing vision config: {e}")
        return jsonify({"error": str(e)}), 500


# ==================== MODEL MANAGEMENT ====================

from src.model_manager import get_model_manager

@app.route('/api/models', methods=['GET'])
def get_llm_models():
    """
    Get list of available LLM/VLM models.

    Returns:
        JSON: {"models": [...], "running": "model_id", "selected": "model_id"}
    """
    try:
        manager = get_model_manager()
        return jsonify({
            "models": manager.get_available_models(),
            "running": manager.get_running_model(),
            "selected": manager.get_selected_model(),
        })
    except Exception as e:
        logger.error(f"Error getting models: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/models/status', methods=['GET'])
def get_model_status():
    """
    Get current model server status.

    Returns:
        JSON: {
            "status": "ready|stopped|error",
            "running_model": "...",
            "selected_model": "...",
            "needs_restart": bool
        }
    """
    try:
        manager = get_model_manager()
        return jsonify(manager.get_status())
    except Exception as e:
        logger.error(f"Error getting model status: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/models/select', methods=['POST'])
def select_llm_model():
    """
    Select a model for next restart.

    This does NOT switch the model live - it saves the selection.
    Server restart is required to apply the change.

    Body (JSON):
        - model_id: Target model preset ID (e.g., "qwen2.5-14b-awq", "qwen2.5-vl-7b")

    Returns:
        JSON: {"status": "saved", "message": "...", "needs_restart": bool}
    """
    try:
        data = request.get_json()
        model_id = data.get('model_id')

        if not model_id:
            return jsonify({"status": "error", "message": "model_id is required"}), 400

        manager = get_model_manager()
        result = manager.select_model(model_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error selecting model: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/models/command', methods=['GET'])
def get_vllm_command():
    """
    Get vLLM start command for the selected model.

    Returns:
        JSON: {"command": "vllm serve ..."}
    """
    try:
        manager = get_model_manager()
        return jsonify({"command": manager.get_vllm_command()})
    except Exception as e:
        logger.error(f"Error getting vLLM command: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/models/log', methods=['GET'])
def get_model_log():
    """
    Get recent vLLM server log output.

    Query params:
        - lines: Number of lines to return (default: 50)

    Returns:
        JSON: {"log": "..."}
    """
    try:
        lines = int(request.args.get('lines', 50))
        manager = get_model_manager()
        return jsonify({"log": manager.get_log(lines=lines)})
    except Exception as e:
        logger.error(f"Error getting model log: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/models/restart', methods=['POST'])
def restart_vllm():
    """
    Restart vLLM server with the selected model.

    This endpoint streams progress updates using Server-Sent Events.

    Returns:
        SSE stream with progress updates:
        - status: stopping|stopped|starting|waiting|ready|error
        - message: Human-readable status message
        - progress: 0-100 percentage
    """
    def generate():
        try:
            manager = get_model_manager()
            for update in manager.restart_vllm():
                yield f"data: {json.dumps(update)}\n\n"
        except Exception as e:
            logger.error(f"Error restarting vLLM: {e}")
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
        }
    )


# ==================== HEALTH CHECK ====================

# ==================== STATIC FILES ====================

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent

@app.route('/icon/<path:filename>')
def serve_icon(filename):
    """Serve character icon files"""
    return send_from_directory(PROJECT_ROOT / 'icon', filename)

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files (HTML, CSS, JS)"""
    return send_from_directory(Path(__file__).parent / 'static', filename)

# Serve duo-gui React app
@app.route('/')
def serve_gui_index():
    """Serve duo-gui React app index"""
    return send_from_directory(PROJECT_ROOT / 'duo-gui' / 'dist', 'index.html')

@app.route('/assets/<path:filename>')
def serve_gui_assets(filename):
    """Serve duo-gui React app assets"""
    return send_from_directory(PROJECT_ROOT / 'duo-gui' / 'dist' / 'assets', filename)


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok"})


# ==================== STARTUP ====================

if __name__ == '__main__':
    import sys

    # Get port from environment or use default
    port = int(os.getenv('FLASK_PORT', 5000))

    print("=" * 70)
    print("🚀 DUO-TALK Backend API Server")
    print("=" * 70)
    print(f"\n📡 Starting API server on http://localhost:{port}")
    print(f"📁 Log directory: {config.log_dir}")
    print(f"📚 RAG data: {config.rag_data_dir}")
    print("\nEndpoints:")
    print(f"  GET  /api/run/list - List all runs")
    print(f"  GET  /api/run/events?run_id=... - Get run events")
    print(f"  GET  /api/run/stream?run_id=... - Stream run events (SSE)")
    print(f"  POST /api/narration/start - Start new narration")
    print(f"  GET  /api/rag/score - Get RAG scores")
    print(f"  GET  /api/feedback/trends - Get feedback trends")
    print(f"  POST /api/feedback/record - Record feedback")
    print(f"  GET  /api/system/status - System status")
    print(f"  GET  /api/vision/config - Get vision config")
    print(f"  POST /api/vision/config - Save vision config")
    print(f"  GET  /api/vision/presets - Get vision presets")
    print(f"  POST /api/vision/presets/apply - Apply preset")
    print(f"  GET  /api/vision/models - Get available models")
    print(f"  POST /api/vision/test - Test vision config")
    print(f"  GET  /health - Health check")
    print("\n" + "=" * 70)

    app.run(host='0.0.0.0', port=port, debug=True)
