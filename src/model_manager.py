"""
Model management: vLLM server start/stop/switch functionality.
"""

import os
import subprocess
import time
from pathlib import Path
from typing import Optional, Dict, List
import requests

from src.config import config


MODEL_PRESETS: Dict[str, dict] = {
    "qwen2.5-14b-awq": {
        "name": "Qwen/Qwen2.5-14B-Instruct-AWQ",
        "vllm_args": [
            "--quantization", "awq",
            "--dtype", "half",
            "--gpu-memory-utilization", "0.90",
            "--max-model-len", "8192",
            "--host", "127.0.0.1",
            "--port", "8000",
        ],
        "supports_vision": False,
        "description": "テキスト対話特化（高品質）",
        "vram_estimate": "22GB",
    },
    "qwen2.5-vl-7b": {
        "name": "Qwen/Qwen2.5-VL-7B-Instruct",
        "vllm_args": [
            "--dtype", "half",
            "--gpu-memory-utilization", "0.90",
            "--max-model-len", "8192",
            "--max-num-seqs", "2",
            "--host", "127.0.0.1",
            "--port", "8000",
            "--trust-remote-code",
            "--enforce-eager",
            "--limit-mm-per-prompt", '{"image": 1}',
        ],
        "supports_vision": True,
        "description": "テキスト+画像対話",
        "vram_estimate": "20GB",
    },
}


class ModelManager:
    """Manages vLLM server lifecycle and model switching."""

    def __init__(self):
        self.current_model: Optional[str] = None
        self.vllm_process: Optional[subprocess.Popen] = None
        self.status = "unknown"
        self._detect_current_model()

    def _detect_current_model(self) -> None:
        """Detect currently running model from vLLM server."""
        try:
            response = requests.get(
                f"{config.openai_base_url.replace('/v1', '')}/v1/models",
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    model_name = data["data"][0]["id"]
                    # Find matching preset
                    for model_id, preset in MODEL_PRESETS.items():
                        if preset["name"] == model_name:
                            self.current_model = model_id
                            self.status = "ready"
                            return
                    # Model is running but not in presets
                    self.current_model = "custom"
                    self.status = "ready"
        except requests.RequestException:
            self.status = "stopped"

    def get_available_models(self) -> List[dict]:
        """Return list of available models."""
        return [
            {
                "id": model_id,
                "name": preset["name"],
                "vision": preset["supports_vision"],
                "description": preset["description"],
                "vram": preset.get("vram_estimate", "N/A"),
                "active": model_id == self.current_model,
            }
            for model_id, preset in MODEL_PRESETS.items()
        ]

    def get_current_model(self) -> Optional[str]:
        """Return current model ID."""
        return self.current_model

    def get_status(self) -> dict:
        """Return current status."""
        preset = MODEL_PRESETS.get(self.current_model, {})
        return {
            "status": self.status,
            "current_model": self.current_model,
            "model_name": preset.get("name", "N/A"),
            "supports_vision": preset.get("supports_vision", False),
        }

    def stop_vllm(self) -> bool:
        """Stop vLLM server."""
        self.status = "stopping"

        # Kill vLLM processes
        subprocess.run(["pkill", "-9", "-f", "vllm serve"], capture_output=True)
        time.sleep(2)

        # Also kill any remaining EngineCore processes
        result = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            for pid in result.stdout.strip().split("\n"):
                pid = pid.strip()
                if pid:
                    subprocess.run(["kill", "-9", pid], capture_output=True)
            time.sleep(2)

        if self.vllm_process:
            try:
                self.vllm_process.terminate()
                self.vllm_process.wait(timeout=5)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                pass
            self.vllm_process = None

        self.current_model = None
        self.status = "stopped"
        return True

    def start_vllm(self, model_id: str, timeout: int = 180) -> bool:
        """
        Start vLLM server with specified model.

        Args:
            model_id: Model preset ID
            timeout: Maximum seconds to wait for startup

        Returns:
            True if started successfully
        """
        if model_id not in MODEL_PRESETS:
            self.status = "error"
            return False

        preset = MODEL_PRESETS[model_id]
        self.status = "starting"

        # Find vllm executable
        vllm_path = self._find_vllm_executable()
        if not vllm_path:
            self.status = "error"
            return False

        # Build command
        cmd = [vllm_path, "serve", preset["name"]] + preset["vllm_args"]

        # Start in background
        log_path = Path("/tmp") / f"vllm_{model_id}.log"
        with open(log_path, "w") as log_file:
            self.vllm_process = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        # Wait for startup
        for i in range(timeout):
            time.sleep(1)
            if self._check_vllm_ready():
                self.current_model = model_id
                self.status = "ready"
                self._update_env_file(preset["name"])
                return True

            # Check if process died
            if self.vllm_process.poll() is not None:
                self.status = "error"
                return False

        self.status = "error"
        return False

    def _find_vllm_executable(self) -> Optional[str]:
        """Find vllm executable path."""
        # Try common locations
        candidates = [
            "/home/owner/miniconda3/envs/duo-talk/bin/vllm",
            "vllm",
        ]
        for path in candidates:
            result = subprocess.run(
                ["which", path] if "/" not in path else ["test", "-x", path],
                capture_output=True
            )
            if result.returncode == 0:
                return path if "/" in path else result.stdout.decode().strip()

        # Fallback: use conda environment path
        return "/home/owner/miniconda3/envs/duo-talk/bin/vllm"

    def _check_vllm_ready(self) -> bool:
        """Check if vLLM is responding."""
        try:
            base_url = config.openai_base_url.replace("/v1", "")
            response = requests.get(f"{base_url}/v1/models", timeout=2)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def _update_env_file(self, model_name: str) -> None:
        """Update .env file with new model name."""
        env_path = Path(__file__).parent.parent / ".env"
        if not env_path.exists():
            return

        lines = env_path.read_text().splitlines()
        new_lines = []
        for line in lines:
            if line.startswith("OPENAI_MODEL="):
                new_lines.append(f"OPENAI_MODEL={model_name}")
            else:
                new_lines.append(line)
        env_path.write_text("\n".join(new_lines) + "\n")

    def switch_model(self, model_id: str) -> dict:
        """
        Switch to a different model.

        Args:
            model_id: Target model preset ID

        Returns:
            Status dict with result
        """
        if model_id not in MODEL_PRESETS:
            return {
                "status": "error",
                "message": f"Unknown model: {model_id}"
            }

        if model_id == self.current_model and self.status == "ready":
            return {
                "status": "already_active",
                "message": "既にこのモデルが起動中です"
            }

        self.status = "switching"
        self.stop_vllm()

        if self.start_vllm(model_id):
            return {
                "status": "success",
                "message": f"{MODEL_PRESETS[model_id]['name']} に切り替えました"
            }
        else:
            return {
                "status": "error",
                "message": "モデルの起動に失敗しました。ログを確認してください。"
            }

    def get_log(self, model_id: Optional[str] = None, lines: int = 50) -> str:
        """Get recent log output."""
        model_id = model_id or self.current_model or "qwen2.5-vl-7b"
        log_path = Path("/tmp") / f"vllm_{model_id}.log"
        if log_path.exists():
            content = log_path.read_text()
            return "\n".join(content.splitlines()[-lines:])
        return "No log available"


# Singleton instance
_model_manager: Optional[ModelManager] = None


def get_model_manager() -> ModelManager:
    """Get or create singleton ModelManager instance."""
    global _model_manager
    if _model_manager is None:
        _model_manager = ModelManager()
    return _model_manager
