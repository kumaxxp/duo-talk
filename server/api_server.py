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

from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import logging

from src.config import config
from src.logger import get_logger
from src.feedback_analyzer import FeedbackAnalyzer
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
    Alternative endpoint for legacy GUI compatibility.

    Body (JSON):
        - topic: Narration topic/scene description
        - model: LLM model to use (e.g., "gemma3:12b")
        - maxTurns: Maximum number of turns (default: 8)
        - seed: Random seed for reproducibility
        - noRag: Boolean, whether to disable RAG (default: false)

    Returns:
        JSON: {"run_id": "...", "topic": "..."}
    """
    from datetime import datetime
    import json as json_module
    import threading

    try:
        data = request.get_json()
        topic = data.get('topic', '')
        model = data.get('model', 'qwen2.5:7b-instruct-q4_K_M')
        max_turns = data.get('maxTurns', 8)
        seed = data.get('seed')
        no_rag = data.get('noRag', False)

        if not topic:
            return jsonify({"error": "topic required"}), 400

        # Generate run ID
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Create run metadata event
        run_event = {
            "event": "narration_start",
            "run_id": run_id,
            "topic": topic,
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

        logger.info(f"Run started: {run_id} - Topic: {topic}")

        # Start narration pipeline in background thread
        def run_pipeline():
            try:
                logger.info(f"Starting pipeline for {run_id}")

                # Initialize pipeline
                pipeline = NarrationPipeline()

                # Process with the topic as scene description (skip vision analysis)
                # Vision分析をスキップし、トピックのみで対話を生成
                result = pipeline.process_image(
                    image_path=None,
                    scene_description=topic,
                    max_iterations=max_turns,
                    run_id=run_id,
                    skip_vision=True,  # トピックのみで対話生成
                )

                # Log completion
                if result.get('status') == 'success':
                    completion_event = {
                        "event": "narration_complete",
                        "run_id": run_id,
                        "topic": topic,
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
            "topic": topic,
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


# ==================== HEALTH CHECK ====================

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
    print(f"  GET  /health - Health check")
    print("\n" + "=" * 70)

    app.run(host='0.0.0.0', port=port, debug=True)
