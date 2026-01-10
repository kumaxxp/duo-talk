"""
API Extensions for Ollama Management
"""

import sys
import httpx
from pathlib import Path
from flask import Blueprint, jsonify, request
from src.config import config

# Blueprint
ollama_api = Blueprint('ollama_api', __name__)

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

# ==================== OLLAMA API ====================

@ollama_api.route('/api/ollama/status', methods=['GET'])
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

@ollama_api.route('/api/ollama/models', methods=['GET'])
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

@ollama_api.route('/api/ollama/select', methods=['POST'])
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
