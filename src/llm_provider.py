"""
LLM Provider - Ollama/vLLM バックエンド抽象化層

設計書: duo_talk_vision_system_design_final_v2.md に基づく実装
"""

import os
import yaml
import requests
import json
import subprocess
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Union
from enum import Enum

from openai import OpenAI
from src.config import config
from src.docker_manager import DockerServiceManager, DockerConfig, ServiceState
from src.model_manager import get_model_manager, MODEL_PRESETS


class BackendType(Enum):
    OLLAMA = "ollama"
    VLLM = "vllm"


@dataclass
class ModelInfo:
    """モデル情報"""
    name: str
    supports_vlm: bool
    quantization: Optional[str]
    vram_estimate_gb: float
    context_length: int
    description: str
    docker_args: List[str] = field(default_factory=list)


@dataclass
class BackendStatus:
    """バックエンド状態"""
    backend: BackendType
    available: bool
    current_model: Optional[str]
    error: Optional[str] = None


class LLMProvider:
    """
    LLMバックエンド抽象化層

    Ollama と vLLM (Docker) を統一インターフェースで切り替え可能にする
    """

    CONFIG_PATH = Path(__file__).parent.parent / "config" / "llm_backends.yaml"
    STATE_PATH = Path(__file__).parent.parent / \
        "config" / "llm_provider_state.json"

    def __init__(self):
        self.config = self._load_config()
        self._client: Optional[OpenAI] = None
        self._current_backend: Optional[BackendType] = None
        self._current_model: Optional[str] = None
        self._docker_container_id: Optional[str] = None

        # 状態復元
        self._restore_state()

    def _load_config(self) -> Dict[str, Any]:
        """設定ファイルを読み込み"""
        if not self.CONFIG_PATH.exists():
            raise FileNotFoundError(f"Config not found: {self.CONFIG_PATH}")

        with open(self.CONFIG_PATH, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def _save_state(self) -> None:
        """現在の状態を保存"""
        import json
        state = {
            "backend": self._current_backend.value if self._current_backend else None,
            "model": self._current_model,
            "container_id": self._docker_container_id
        }
        self.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.STATE_PATH.write_text(json.dumps(state, indent=2))

    def _restore_state(self) -> None:
        """状態を復元"""
        import json
        if self.STATE_PATH.exists():
            try:
                state = json.loads(self.STATE_PATH.read_text())
                if state.get("backend"):
                    self._current_backend = BackendType(state["backend"])
                self._current_model = state.get("model")
                self._docker_container_id = state.get("container_id")
            except (json.JSONDecodeError, ValueError):
                pass

    # ========== バックエンド情報取得 ==========

    def get_available_backends(self) -> List[Dict[str, Any]]:
        """利用可能なバックエンド一覧を取得"""
        backends = []
        for backend_id, backend_config in self.config.get("backends", {}).items():
            if not backend_config.get("enabled", True):
                continue

            models = []
            for model_id, model_config in backend_config.get("models", {}).items():
                models.append({
                    "id": model_id,
                    "name": model_config["name"],
                    "supports_vlm": model_config.get("supports_vlm", False),
                    "vram_gb": model_config.get("vram_estimate_gb", 0),
                    "description": model_config.get("description", ""),
                })

            backends.append({
                "id": backend_id,
                "base_url": backend_config["base_url"],
                "models": models,
                "is_current": self._current_backend and self._current_backend.value == backend_id,
            })

        return backends

    def get_backend_config(self, backend: BackendType) -> Dict[str, Any]:
        """指定バックエンドの設定を取得"""
        return self.config.get("backends", {}).get(backend.value, {})

    def get_model_info(self, backend: BackendType, model_id: str) -> Optional[ModelInfo]:
        """モデル情報を取得"""
        backend_config = self.get_backend_config(backend)
        model_config = backend_config.get("models", {}).get(model_id)

        if not model_config:
            return None

        return ModelInfo(
            name=model_config["name"],
            supports_vlm=model_config.get("supports_vlm", False),
            quantization=model_config.get("quantization"),
            vram_estimate_gb=model_config.get("vram_estimate_gb", 0),
            context_length=model_config.get("context_length", 4096),
            description=model_config.get("description", ""),
            docker_args=model_config.get("docker_args", []),
        )

    # ========== 接続状態確認 ==========

    def check_backend_health(self, backend: BackendType) -> BackendStatus:
        """バックエンドの接続状態を確認"""
        backend_config = self.get_backend_config(backend)
        health_url = backend_config.get("health_check_url")

        if not health_url:
            return BackendStatus(backend, False, None, "No health check URL configured")

        try:
            response = requests.get(health_url, timeout=5)
            if response.status_code == 200:
                # 現在のモデルを取得
                current_model = self._get_running_model(backend)
                return BackendStatus(backend, True, current_model)
            else:
                return BackendStatus(backend, False, None, f"HTTP {response.status_code}")
        except requests.RequestException as e:
            return BackendStatus(backend, False, None, str(e))

    def _get_running_model(self, backend: BackendType) -> Optional[str]:
        """現在実行中のモデルを取得"""
        backend_config = self.get_backend_config(backend)
        base_url = backend_config.get("base_url", "").replace("/v1", "")

        try:
            response = requests.get(f"{base_url}/v1/models", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    return data["data"][0]["id"]
        except requests.RequestException:
            pass
        return None

    def get_status(self) -> Dict[str, Any]:
        """現在の状態を取得"""
        ollama_status = self.check_backend_health(BackendType.OLLAMA)
        vllm_status = self.check_backend_health(BackendType.VLLM)

        # Get Florence-2 status via DockerServiceManager
        florence_status = None
        try:
            with DockerServiceManager() as dm:
                f_stat = dm.florence_status()
                florence_status = {
                    "available": f_stat.state.value == "running",
                    "state": f_stat.state.value,
                    "container_id": f_stat.container_id,
                    "gpu_memory_gb": f_stat.gpu_memory_gb
                }
        except Exception as e:
            florence_status = {"available": False, "error": str(e)}

        return {
            "current_backend": self._current_backend.value if self._current_backend else None,
            "current_model": self._current_model,
            "ollama": {
                "available": ollama_status.available,
                "running_model": ollama_status.current_model,
                "error": ollama_status.error,
            },
            "vllm": {
                "available": vllm_status.available,
                "running_model": vllm_status.current_model,
                "error": vllm_status.error,
                "container_id": self._docker_container_id,
            },
            "florence2": florence_status,
            "defaults": self.config.get("defaults", {}),
        }

    # ========== クライアント取得 ==========

    def get_client(self) -> OpenAI:
        """現在のバックエンド用OpenAIクライアントを取得"""
        if self._client is None:
            self._initialize_client()
        return self._client

    def _initialize_client(self) -> None:
        """クライアントを初期化"""
        if self._current_backend is None:
            # デフォルトバックエンドを使用
            defaults = self.config.get("defaults", {})
            backend_name = defaults.get("backend", "vllm")
            self._current_backend = BackendType(backend_name)

            # .envの設定を優先
            self._current_model = config.openai_model or defaults.get("model")

        backend_config = self.get_backend_config(self._current_backend)
        base_url = backend_config.get("base_url", "http://localhost:8000/v1")

        self._client = OpenAI(
            base_url=base_url,
            api_key="not-needed",
            timeout=60,
        )

    def get_model_name(self) -> str:
        """現在のモデル名を取得（API呼び出し用）"""
        if self._current_model is None:
            defaults = self.config.get("defaults", {})
            self._current_model = defaults.get("model", "gemma3-12b-int8")

        if self._current_backend is None:
            defaults = self.config.get("defaults", {})
            self._current_backend = BackendType(
                defaults.get("backend", "vllm"))

        model_info = self.get_model_info(
            self._current_backend, self._current_model)
        return model_info.name if model_info else self._current_model

    # ========== バックエンド切り替え ==========

    def switch_backend(
        self,
        backend: BackendType,
        model_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        バックエンドを切り替え

        Args:
            backend: 切り替え先バックエンド
            model_id: 使用するモデルID（省略時はデフォルト）

        Returns:
            切り替え結果
        """
        # モデルID決定
        if model_id is None:
            defaults = self.config.get("defaults", {})
            if backend == BackendType.OLLAMA:
                model_id = defaults.get("fallback_model", "gemma3-12b")
            else:
                model_id = defaults.get("model", "gemma3-12b-int8")

        # モデル存在確認
        model_info = self.get_model_info(backend, model_id)
        if model_info is None:
            return {
                "success": False,
                "error": f"Unknown model: {model_id} for {backend.value}"
            }

        # バックエンド接続確認
        status = self.check_backend_health(backend)
        if not status.available:
            return {
                "success": False,
                "error": f"{backend.value} is not available: {status.error}",
                "hint": self._get_start_hint(backend, model_id)
            }

        # 切り替え実行
        self._current_backend = backend
        self._current_model = model_id
        self._client = None  # 再初期化を強制

        self._save_state()

        return {
            "success": True,
            "backend": backend.value,
            "model_id": model_id,
            "model_name": model_info.name,
            "supports_vlm": model_info.supports_vlm,
        }

    def _get_start_hint(self, backend: BackendType, model_id: str) -> str:
        """バックエンド起動のヒントを生成"""
        if backend == BackendType.OLLAMA:
            return "Ollamaを起動してください: ollama serve"

        # vLLM Docker
        return self.get_docker_command(model_id)

    # ========== vLLM Docker管理 ==========

    def get_docker_command(self, model_id: str) -> str:
        """vLLM Docker起動コマンドを生成"""
        model_info = self.get_model_info(BackendType.VLLM, model_id)
        if model_info is None:
            return f"# Unknown model: {model_id}"

        docker_config = self.get_backend_config(
            BackendType.VLLM).get("docker", {})

        cmd_parts = [
            "docker run --rm --gpus all",
            f"-v {docker_config.get('cache_mount', '~/.cache/huggingface:/root/.cache/huggingface')}",
            "-p 8000:8000",
        ]

        if docker_config.get("ipc_host", True):
            cmd_parts.append("--ipc=host")

        cmd_parts.append(docker_config.get("image", "vllm/vllm-openai:latest"))
        cmd_parts.append(f"--model {model_info.name}")

        gpu_util = docker_config.get("gpu_memory_utilization", 0.85)
        cmd_parts.append(f"--gpu-memory-utilization {gpu_util}")

        # モデル固有の引数
        for arg in model_info.docker_args:
            cmd_parts.append(arg)

        return " \\\n    ".join(cmd_parts)

    def start_vllm_docker(self, model_id: str) -> Dict[str, Any]:
        """vLLM Dockerコンテナを起動 (Unified with DockerServiceManager)"""
        if model_id not in MODEL_PRESETS:
            return {"success": False, "error": f"Unknown model: {model_id}"}
        
        # 1. Update .env via ModelManager to ensure persistence
        get_model_manager().select_model(model_id)
        
        # 2. Extract configuration from preset
        preset = MODEL_PRESETS[model_id]
        vllm_args = preset.get("vllm_args", [])
        
        # Parse args for DockerConfig
        gpu_util = 0.85
        max_len = 8192
        
        try:
            if "--gpu-memory-utilization" in vllm_args:
                idx = vllm_args.index("--gpu-memory-utilization")
                gpu_util = float(vllm_args[idx + 1])
            
            if "--max-model-len" in vllm_args:
                idx = vllm_args.index("--max-model-len")
                max_len = int(vllm_args[idx + 1])
        except (ValueError, IndexError):
            pass

        # 3. Initialize DockerServiceManager with custom config
        d_cfg = DockerConfig(
            vllm_model=preset["name"],
            vllm_gpu_memory=gpu_util,
            vllm_max_model_len=max_len,
            # Ensure we use standard container names
            vllm_container="duo-talk-vllm"
        )
        
        try:
            # We use the manager to start vLLM
            # Note: start_vllm returns boolean success
            with DockerServiceManager(config=d_cfg) as dm:
                success = dm.start_vllm()
                status = dm.vllm_status()
                
                if success:
                    # Update local state
                    self._docker_container_id = status.container_id
                    self._save_state()
                    
                    return {
                        "success": True,
                        "container_id": status.container_id,
                        "message": "Container started successfully.",
                        "model": preset["name"],
                    }
                else:
                    return {
                        "success": False,
                        "error": "Failed to start vLLM container. Check docker logs."
                    }
                    
        except Exception as e:
            return {"success": False, "error": str(e)}

    def stop_vllm_docker(self) -> Dict[str, Any]:
        """vLLM Dockerコンテナを停止"""
        if not self._docker_container_id:
            # コンテナIDがない場合、実行中のvLLMコンテナを探す
            try:
                result = subprocess.run(
                    ["docker", "ps", "-q", "--filter",
                        "ancestor=vllm/vllm-openai:latest"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    self._docker_container_id = result.stdout.strip().split('\n')[
                        0]
            except Exception:
                pass

        if not self._docker_container_id:
            return {"success": True, "message": "No container running"}

        try:
            result = subprocess.run(
                ["docker", "stop", self._docker_container_id],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                old_id = self._docker_container_id
                self._docker_container_id = None
                self._save_state()
                return {"success": True, "stopped_container": old_id}
            else:
                return {"success": False, "error": result.stderr}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def wait_for_vllm_ready(self, timeout: int = 180) -> bool:
        """vLLMサーバーの起動完了を待機"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            status = self.check_backend_health(BackendType.VLLM)
            if status.available:
                return True
            time.sleep(3)
        return False

    # ========== Florence-2 Docker Management ==========

    def start_florence_docker(self) -> Dict[str, Any]:
        """Florence-2 Dockerコンテナを起動"""
        try:
            with DockerServiceManager() as dm:
                if dm.start_florence():
                    return {"success": True, "message": "Florence-2 started"}
                else:
                    return {"success": False, "error": "Failed to start Florence-2"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def stop_florence_docker(self) -> Dict[str, Any]:
        """Florence-2 Dockerコンテナを停止"""
        try:
            with DockerServiceManager() as dm:
                if dm.stop_florence():
                    return {"success": True, "message": "Florence-2 stopped"}
                else:
                    return {"success": False, "error": "Failed to stop Florence-2"}
        except Exception as e:
            return {"success": False, "error": str(e)}


# シングルトン
_provider: Optional[LLMProvider] = None


def get_llm_provider() -> LLMProvider:
    """シングルトンインスタンスを取得"""
    global _provider
    if _provider is None:
        _provider = LLMProvider()
    return _provider


def reset_llm_provider() -> None:
    """シングルトンをリセット（テスト用）"""
    global _provider
    _provider = None
