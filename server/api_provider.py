"""
API Extensions for LLM Provider Management (vLLM/Ollama/Docker)
"""

import sys
import json
import os
import time
import httpx
from pathlib import Path
from typing import Optional, Dict, Any, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Blueprint, jsonify, request
from src.config import config
from src.docker_manager import DockerServiceManager, ServiceState

# Blueprint
provider_api = Blueprint('provider_api', __name__)

# Global Docker Manager
_docker_manager: Optional[DockerServiceManager] = None

def get_docker_manager() -> DockerServiceManager:
    global _docker_manager
    if _docker_manager is None:
        _docker_manager = DockerServiceManager()
    return _docker_manager

# ==================== HELPER FUNCTIONS ====================

def update_env_file(key: str, value: str):
    """Update a key in the .env file"""
    env_path = config.project_root / ".env"
    if not env_path.exists():
        return

    lines = env_path.read_text().splitlines()
    new_lines = []
    found = False
    
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)
    
    if not found:
        new_lines.append(f"{key}={value}")
    
    env_path.write_text("\n".join(new_lines) + "\n")

# ==================== PROVIDER API ====================

@provider_api.route('/api/v2/provider/status', methods=['GET'])
def get_provider_status():
    """Get status of all providers"""
    manager = get_docker_manager()
    docker_status = manager.status()
    
    # Check Ollama
    ollama_health = {
        "available": False,
        "running_model": None,
        "error": None
    }
    
    try:
        # Check basic connectivity
        resp = httpx.get("http://localhost:11434/api/tags", timeout=1.0)
        if resp.status_code == 200:
            ollama_health["available"] = True
            
            # Try to get currently loaded model if possible (Ollama API doesn't always expose this cleanly)
            # We can infer it from 'ps' if available in newer versions
            try:
                ps_resp = httpx.get("http://localhost:11434/api/ps", timeout=1.0)
                if ps_resp.status_code == 200:
                    models = ps_resp.json().get('models', [])
                    if models:
                        ollama_health["running_model"] = models[0].get('name')
            except Exception:
                pass
    except Exception as e:
        ollama_health["error"] = str(e)

    # Determine current backend based on config
    current_url = config.openai_base_url
    current_backend = "unknown"
    
    if "11434" in current_url:
        current_backend = "ollama"
    elif "8000" in current_url:
        current_backend = "vllm"

    return jsonify({
        "current_backend": current_backend,
        "current_model": config.openai_model,
        "ollama": ollama_health,
        "vllm": {
            "available": docker_status["vllm"].state == ServiceState.RUNNING,
            "running_model": manager.config.vllm_model if docker_status["vllm"].state == ServiceState.RUNNING else None,
            "error": docker_status["vllm"].error,
            "container_id": docker_status["vllm"].container_id
        },
        "defaults": {
            "backend": "vllm", # Default preference
            "model": "qwen2.5-vl-7b",
            "fallback_backend": "ollama",
            "fallback_model": "mistral"
        }
    })

@provider_api.route('/api/v2/provider/backends', methods=['GET'])
def get_backends():
    """Get available backends and models"""
    # Hardcoded for now based on what we know supports
    
    # 1. vLLM Models (matched with DockerConfig or presets)
    vllm_models = [
        {"id": "qwen2.5-vl-7b", "name": "Qwen2.5-VL-7B", "supports_vlm": True, "vram_gb": 18, "description": "Standard VLM"},
        {"id": "gemma3-12b-int8", "name": "Gemma 3 12B (Int8)", "supports_vlm": True, "vram_gb": 14, "description": "High Performance VLM"}, 
        {"id": "gemma3-27b-int4", "name": "Gemma 3 27B (Int4)", "supports_vlm": True, "vram_gb": 16, "description": "Large VLM"}
    ]

    # 2. Ollama Models
    ollama_models = []
    try:
        resp = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        if resp.status_code == 200:
            data = resp.json()
            for m in data.get('models', []):
                name = m.get('name')
                details = m.get('details', {})
                ollama_models.append({
                    "id": name,
                    "name": name,
                    "supports_vlm": "llava" in name or "vision" in name, # Rough heuristic
                    "vram_gb": round(m.get('size', 0) / (1024**3), 1),
                    "description": f"{details.get('parameter_size', '?')} params"
                })
    except Exception:
        pass

    return jsonify({
        "backends": [
            {
                "id": "ollama",
                "base_url": "http://localhost:11434/v1",
                "is_current": "11434" in config.openai_base_url,
                "models": ollama_models
            },
            {
                "id": "vllm",
                "base_url": "http://localhost:8000/v1",
                "is_current": "8000" in config.openai_base_url,
                "models": vllm_models
            }
        ]
    })

@provider_api.route('/api/v2/provider/switch', methods=['POST'])
def switch_provider():
    """Switch backend provider"""
    data = request.get_json()
    backend = data.get('backend')
    model_id = data.get('model_id')
    
    if backend not in ['ollama', 'vllm']:
        return jsonify({"success": False, "error": "Invalid backend"}), 400

    new_url = ""
    new_model = ""

    if backend == "ollama":
        new_url = "http://localhost:11434/v1"
        new_model = model_id or "mistral"
    elif backend == "vllm":
        new_url = "http://localhost:8000/v1"
        new_model = model_id or "qwen2.5-vl-7b"
        
        # Note: If switching to vLLM, we might need to ensure Docker is running with correct model
        # For now, we just switch config. The user might need to restart Docker via UI.
    
    # Update .env
    update_env_file("OPENAI_BASE_URL", new_url)
    update_env_file("OPENAI_MODEL", new_model)
    
    # Update runtime config (best effort)
    config.openai_base_url = new_url
    config.openai_model = new_model

    return jsonify({
        "success": True, 
        "hint": "Configuration updated. Restart server if changes don't reflect immediately."
    })

@provider_api.route('/api/v2/provider/docker/start', methods=['POST'])
def docker_start():
    """Start vLLM Docker"""
    data = request.get_json() or {}
    model_id = data.get('model_id')
    
    manager = get_docker_manager()
    
    # If model_id provided, we might want to update config?
    # DockerManager currently uses its own config defaults or passed in config
    # For now, we just start all. 
    # TODO: Pass model selection to DockerManager if supported dynamically
    
    success = manager.start_all()
    
    if success:
        return jsonify({"success": True})
    else:
        logs = manager.get_logs("vllm", tail=20)
        return jsonify({
            "success": False, 
            "error": "Failed to start services", 
            "logs": logs
        }), 500

@provider_api.route('/api/v2/provider/docker/stop', methods=['POST'])
def docker_stop():
    """Stop vLLM Docker"""
    manager = get_docker_manager()
    success = manager.stop_all()
    return jsonify({"success": success})

@provider_api.route('/api/v2/provider/docker/command/<model_id>', methods=['GET'])
def get_docker_command(model_id):
    """Get the raw docker run command for reference"""
    # Just constructing it for display
    cmd = f"docker run -d --gpus all -p 8000:8000 -v ~/.cache/huggingface:/root/.cache/huggingface --ipc=host vllm/vllm-openai:latest --model {model_id}"
    return jsonify({"command": cmd})


# ==================== OLLAMA API (Settings Panel) ====================

@provider_api.route('/api/ollama/status', methods=['GET'])
def get_ollama_status():
    """Ollama specific status"""
    try:
        resp = httpx.get("http://localhost:11434/api/tags", timeout=1.0)
        status = "ready" if resp.status_code == 200 else "error"
    except:
        status = "stopped"
        
    return jsonify({
        "status": status,
        "model": config.openai_model if "11434" in config.openai_base_url else None,
        "backend": "ollama",
        "base_url": "http://localhost:11434"
    })

@provider_api.route('/api/ollama/models', methods=['GET'])
def get_ollama_models():
    """Get raw list of ollama models"""
    models = []
    try:
        resp = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        if resp.status_code == 200:
            data = resp.json()
            for m in data.get('models', []):
                models.append({
                    "name": m.get('name'),
                    "size": f"{round(m.get('size', 0)/1024**3, 1)}GB",
                    "family": m.get('details', {}).get('family', 'unknown'),
                    "params": m.get('details', {}).get('parameter_size', '?'),
                    "vision": "vision" in m.get('details', {}).get('families', []) or "llava" in m.get('name', '')
                })
    except:
        pass
        
    return jsonify({"models": models})

@provider_api.route('/api/ollama/select', methods=['POST'])
def select_ollama_model():
    """Select specific Ollama model"""
    data = request.get_json()
    model = data.get('model')
    
    if not model:
        return jsonify({"status": "error", "message": "Model required"}), 400

    # Switch to Ollama mode and set model
    update_env_file("OPENAI_BASE_URL", "http://localhost:11434/v1")
    update_env_file("OPENAI_MODEL", model)
    
    config.openai_base_url = "http://localhost:11434/v1"
    config.openai_model = model
    
    return jsonify({"status": "ok", "message": f"Selected {model}"})
