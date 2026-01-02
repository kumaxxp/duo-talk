"""
Model management: vLLM server configuration and status.

This module manages model configuration including vLLM server restart.
"""

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional, Dict, List, Generator
import requests

from src.config import config

# Config file for selected model
MODEL_CONFIG_PATH = Path(__file__).parent.parent / "config" / "model_config.json"


MODEL_PRESETS: Dict[str, dict] = {
    # === VLM (Vision) Models ===
    "gemma3-27b-int4": {
        "name": "RedHatAI/gemma-3-27b-it-quantized.w4a16",
        "vllm_args": [
            "--dtype", "bfloat16",
            "--gpu-memory-utilization", "0.90",
            "--max-model-len", "4096",
            "--max-num-seqs", "2",
            "--host", "127.0.0.1",
            "--port", "8000",
            "--trust-remote-code",
            "--enforce-eager",
            "--limit-mm-per-prompt", '{"image": 1}',
        ],
        "supports_vision": True,
        "description": "高精度VLM（INT4 W4A16）",
        "vram_estimate": "16GB",
        "verified": False,
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
        "vram_estimate": "18GB",
        "verified": True,
    },
    "gemma3-12b": {
        "name": "google/gemma-3-12b-it",
        "vllm_args": [
            "--dtype", "bfloat16",
            "--gpu-memory-utilization", "0.90",
            "--max-model-len", "4096",
            "--max-num-seqs", "2",
            "--host", "127.0.0.1",
            "--port", "8000",
            "--trust-remote-code",
            "--enforce-eager",
            "--limit-mm-per-prompt", '{"image": 1}',
        ],
        "supports_vision": True,
        "description": "バランス型VLM",
        "vram_estimate": "14GB",
        "verified": False,  # OOM on 24GB GPU - requires ~23GB
    },
    # === Text-only Models ===
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
        "description": "高品質テキスト対話",
        "vram_estimate": "12GB",
        "verified": True,
    },
    "qwen2.5-7b-awq": {
        "name": "Qwen/Qwen2.5-7B-Instruct-AWQ",
        "vllm_args": [
            "--quantization", "awq",
            "--dtype", "half",
            "--gpu-memory-utilization", "0.90",
            "--max-model-len", "8192",
            "--host", "127.0.0.1",
            "--port", "8000",
        ],
        "supports_vision": False,
        "description": "軽量テキスト対話",
        "vram_estimate": "6GB",
        "verified": True,
    },
    "qwen2.5-3b": {
        "name": "Qwen/Qwen2.5-3B-Instruct",
        "vllm_args": [
            "--dtype", "half",
            "--gpu-memory-utilization", "0.90",
            "--max-model-len", "8192",
            "--host", "127.0.0.1",
            "--port", "8000",
        ],
        "supports_vision": False,
        "description": "最軽量（フォールバック）",
        "vram_estimate": "4GB",
        "verified": True,
    },
}


class ModelManager:
    """
    Manages vLLM model configuration.

    Model switching requires server restart - this class only manages configuration.
    """

    def __init__(self):
        self.running_model: Optional[str] = None
        self.status = "unknown"
        self._detect_running_model()

    def _detect_running_model(self) -> None:
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
                            self.running_model = model_id
                            self.status = "ready"
                            return
                    # Model is running but not in presets
                    self.running_model = "custom"
                    self.status = "ready"
        except requests.RequestException:
            self.status = "stopped"

    def _load_selected_model(self) -> Optional[str]:
        """Load selected model from config file."""
        if MODEL_CONFIG_PATH.exists():
            try:
                data = json.loads(MODEL_CONFIG_PATH.read_text())
                return data.get("selected_model")
            except (json.JSONDecodeError, KeyError):
                pass
        return None

    def _save_selected_model(self, model_id: str) -> None:
        """Save selected model to config file."""
        MODEL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {"selected_model": model_id}
        MODEL_CONFIG_PATH.write_text(json.dumps(data, indent=2))

    def get_available_models(self) -> List[dict]:
        """Return list of available models."""
        selected = self._load_selected_model()
        return [
            {
                "id": model_id,
                "name": preset["name"],
                "vision": preset["supports_vision"],
                "description": preset["description"],
                "vram": preset.get("vram_estimate", "N/A"),
                "verified": preset.get("verified", True),
                "running": model_id == self.running_model,
                "selected": model_id == selected if selected else model_id == self.running_model,
            }
            for model_id, preset in MODEL_PRESETS.items()
        ]

    def get_running_model(self) -> Optional[str]:
        """Return currently running model ID."""
        return self.running_model

    def get_selected_model(self) -> Optional[str]:
        """Return selected model ID (may differ from running)."""
        return self._load_selected_model() or self.running_model

    def get_status(self) -> dict:
        """Return current status including restart requirement."""
        running_preset = MODEL_PRESETS.get(self.running_model, {})
        selected = self._load_selected_model()
        selected_preset = MODEL_PRESETS.get(selected, {}) if selected else running_preset

        needs_restart = selected is not None and selected != self.running_model

        return {
            "status": self.status,
            "running_model": self.running_model,
            "running_model_name": running_preset.get("name", "N/A"),
            "supports_vision": running_preset.get("supports_vision", False),
            "selected_model": selected or self.running_model,
            "selected_model_name": selected_preset.get("name", running_preset.get("name", "N/A")),
            "needs_restart": needs_restart,
        }

    def select_model(self, model_id: str) -> dict:
        """
        Select a model for next restart.

        This does NOT switch the model - it only saves the selection.
        Server restart is required to apply the change.
        """
        if model_id not in MODEL_PRESETS:
            return {
                "status": "error",
                "message": f"Unknown model: {model_id}"
            }

        self._save_selected_model(model_id)

        # Update .env file for next startup
        preset = MODEL_PRESETS[model_id]
        self._update_env_file(preset["name"])

        if model_id == self.running_model:
            return {
                "status": "no_change",
                "message": "既にこのモデルが起動中です"
            }

        return {
            "status": "saved",
            "message": f"{preset['name']} を選択しました。サーバー再起動後に適用されます。",
            "needs_restart": True,
            "start_command": self.get_vllm_command(model_id),
        }

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

    def get_vllm_command(self, model_id: Optional[str] = None) -> str:
        """Generate vLLM start command for the specified or selected model."""
        model_id = model_id or self._load_selected_model() or self.running_model or "qwen2.5-vl-7b"

        if model_id not in MODEL_PRESETS:
            return "# Unknown model"

        preset = MODEL_PRESETS[model_id]
        vllm_path = "/home/owner/miniconda3/envs/duo-talk/bin/vllm"

        args = [vllm_path, "serve", preset["name"]] + preset["vllm_args"]

        # Format as shell command with line breaks for readability
        cmd_parts = [args[0], args[1], args[2]]
        for i in range(3, len(args), 2):
            if i + 1 < len(args):
                cmd_parts.append(f"  {args[i]} {args[i+1]}")
            else:
                cmd_parts.append(f"  {args[i]}")

        return " \\\n".join(cmd_parts)

    def get_log(self, model_id: Optional[str] = None, lines: int = 50) -> str:
        """Get recent log output."""
        model_id = model_id or self.running_model or "qwen2.5-vl-7b"
        log_path = Path("/tmp") / f"vllm_{model_id}.log"
        if log_path.exists():
            content = log_path.read_text()
            return "\n".join(content.splitlines()[-lines:])
        return "No log available"

    def _find_vllm_pids(self) -> List[int]:
        """Find PIDs of running vLLM processes."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "vllm serve"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return [int(pid) for pid in result.stdout.strip().split("\n") if pid]
        except (subprocess.SubprocessError, ValueError):
            pass
        return []

    def _kill_vllm(self) -> bool:
        """Kill all running vLLM processes."""
        pids = self._find_vllm_pids()
        if not pids:
            return True

        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

        # Wait for graceful shutdown
        for _ in range(30):  # 30 seconds max
            time.sleep(1)
            if not self._find_vllm_pids():
                return True

        # Force kill if still running
        for pid in self._find_vllm_pids():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

        time.sleep(1)
        return len(self._find_vllm_pids()) == 0

    def _wait_for_vllm_ready(self, timeout: int = 180) -> bool:
        """Wait for vLLM server to become ready."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(
                    "http://127.0.0.1:8000/v1/models",
                    timeout=3
                )
                if response.status_code == 200:
                    return True
            except requests.RequestException:
                pass
            time.sleep(2)
        return False

    def restart_vllm(self) -> Generator[Dict, None, None]:
        """
        Restart vLLM with the selected model.

        Yields progress updates as dictionaries.
        """
        model_id = self._load_selected_model() or self.running_model or "qwen2.5-vl-7b"

        if model_id not in MODEL_PRESETS:
            yield {"status": "error", "message": f"Unknown model: {model_id}"}
            return

        preset = MODEL_PRESETS[model_id]
        model_name = preset["name"]

        # Step 1: Stop current vLLM
        yield {"status": "stopping", "message": "vLLMを停止中...", "progress": 10}

        if not self._kill_vllm():
            yield {"status": "error", "message": "vLLMの停止に失敗しました"}
            return

        self.status = "stopped"
        self.running_model = None
        yield {"status": "stopped", "message": "vLLMを停止しました", "progress": 20}

        # Step 2: Start new vLLM
        yield {"status": "starting", "message": f"{model_name} を起動中...", "progress": 30}

        vllm_path = "/home/owner/miniconda3/envs/duo-talk/bin/vllm"
        log_path = Path("/tmp") / f"vllm_{model_id}.log"

        # Build command
        cmd = [vllm_path, "serve", model_name] + preset["vllm_args"]

        # Start vLLM in background
        with open(log_path, "w") as log_file:
            subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                cwd=str(Path(__file__).parent.parent),
            )

        yield {"status": "waiting", "message": "vLLMの起動を待機中（最大3分）...", "progress": 50}

        # Step 3: Wait for ready
        if self._wait_for_vllm_ready(timeout=180):
            self.running_model = model_id
            self.status = "ready"
            yield {
                "status": "ready",
                "message": f"{model_name} の起動が完了しました",
                "progress": 100,
                "model_id": model_id,
                "model_name": model_name,
            }
        else:
            self.status = "error"
            yield {
                "status": "error",
                "message": "vLLMの起動がタイムアウトしました。ログを確認してください。",
                "log": self.get_log(model_id, lines=30)
            }


# Singleton instance
_model_manager: Optional[ModelManager] = None


def get_model_manager() -> ModelManager:
    """Get or create singleton ModelManager instance."""
    global _model_manager
    if _model_manager is None:
        _model_manager = ModelManager()
    return _model_manager
