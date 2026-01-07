"""
Docker Service Manager for duo-talk

Manages vLLM and Florence-2 Docker containers programmatically.

Usage:
    from src.docker_manager import DockerServiceManager
    
    manager = DockerServiceManager()
    
    # Check status
    status = manager.status()
    print(status)
    
    # Ensure services are running
    manager.ensure_running()
    
    # Stop all services
    manager.stop_all()
"""

import subprocess
import time
import httpx
from dataclasses import dataclass
from typing import Optional, Dict, Any
from enum import Enum


class ServiceState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class ServiceStatus:
    name: str
    state: ServiceState
    port: Optional[int] = None
    container_id: Optional[str] = None
    gpu_memory_gb: Optional[float] = None
    error: Optional[str] = None


@dataclass
class DockerConfig:
    """Docker service configuration"""
    # Container names
    vllm_container: str = "duo-talk-vllm"
    florence_container: str = "duo-talk-florence2"
    florence_image: str = "duo-talk-florence2"
    
    # Ports
    vllm_port: int = 8000
    florence_port: int = 5001
    
    # vLLM settings
    vllm_model: str = "RedHatAI/gemma-3-12b-it-quantized.w8a8"
    vllm_gpu_memory: float = 0.85
    vllm_max_model_len: int = 8192
    
    # Timeouts
    vllm_startup_timeout: int = 300
    florence_startup_timeout: int = 180
    health_check_interval: int = 5


class DockerServiceManager:
    """Manages duo-talk Docker services"""
    
    def __init__(self, config: Optional[DockerConfig] = None):
        self.config = config or DockerConfig()
        self._http_client = httpx.Client(timeout=10.0)
    
    # ============================================================
    # Status Checks
    # ============================================================
    
    def _run_docker(self, *args) -> subprocess.CompletedProcess:
        """Run docker command"""
        return subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True
        )
    
    def _container_exists(self, name: str) -> bool:
        """Check if container exists (running or stopped)"""
        result = self._run_docker("ps", "-a", "--format", "{{.Names}}")
        return name in result.stdout.split("\n")
    
    def _container_running(self, name: str) -> bool:
        """Check if container is running"""
        result = self._run_docker("ps", "--format", "{{.Names}}")
        return name in result.stdout.split("\n")
    
    def _get_container_id(self, name: str) -> Optional[str]:
        """Get container ID"""
        result = self._run_docker("ps", "-a", "--filter", f"name={name}", "--format", "{{.ID}}")
        return result.stdout.strip() or None
    
    def vllm_status(self) -> ServiceStatus:
        """Get vLLM service status"""
        name = self.config.vllm_container
        port = self.config.vllm_port
        
        if not self._container_running(name):
            return ServiceStatus(name=name, state=ServiceState.STOPPED, port=port)
        
        container_id = self._get_container_id(name)
        
        # Check health endpoint
        try:
            resp = self._http_client.get(f"http://localhost:{port}/v1/models")
            if resp.status_code == 200:
                return ServiceStatus(
                    name=name,
                    state=ServiceState.RUNNING,
                    port=port,
                    container_id=container_id,
                )
        except Exception:
            pass
        
        return ServiceStatus(
            name=name,
            state=ServiceState.STARTING,
            port=port,
            container_id=container_id,
        )
    
    def florence_status(self) -> ServiceStatus:
        """Get Florence-2 service status"""
        name = self.config.florence_container
        port = self.config.florence_port
        
        if not self._container_running(name):
            return ServiceStatus(name=name, state=ServiceState.STOPPED, port=port)
        
        container_id = self._get_container_id(name)
        
        # Check health endpoint
        try:
            resp = self._http_client.get(f"http://localhost:{port}/health")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("model_loaded"):
                    return ServiceStatus(
                        name=name,
                        state=ServiceState.RUNNING,
                        port=port,
                        container_id=container_id,
                        gpu_memory_gb=data.get("gpu_memory_gb"),
                    )
        except Exception:
            pass
        
        return ServiceStatus(
            name=name,
            state=ServiceState.STARTING,
            port=port,
            container_id=container_id,
        )
    
    def status(self) -> Dict[str, ServiceStatus]:
        """Get status of all services"""
        return {
            "vllm": self.vllm_status(),
            "florence": self.florence_status(),
        }
    
    def is_all_running(self) -> bool:
        """Check if all services are running"""
        status = self.status()
        return all(s.state == ServiceState.RUNNING for s in status.values())
    
    # ============================================================
    # Stop Functions
    # ============================================================
    
    def stop_container(self, name: str) -> bool:
        """Stop a container"""
        if self._container_running(name):
            result = self._run_docker("stop", name)
            return result.returncode == 0
        return True
    
    def remove_container(self, name: str) -> bool:
        """Remove a container"""
        if self._container_exists(name):
            result = self._run_docker("rm", name)
            return result.returncode == 0
        return True
    
    def stop_vllm(self) -> bool:
        """Stop vLLM container"""
        return self.stop_container(self.config.vllm_container)
    
    def stop_florence(self) -> bool:
        """Stop Florence-2 container"""
        return self.stop_container(self.config.florence_container)
    
    def stop_all(self) -> bool:
        """Stop all services"""
        success = True
        success = self.stop_florence() and success
        success = self.stop_vllm() and success
        return success
    
    def clean_all(self) -> bool:
        """Stop and remove all containers"""
        success = self.stop_all()
        success = self.remove_container(self.config.florence_container) and success
        success = self.remove_container(self.config.vllm_container) and success
        return success
    
    # ============================================================
    # Start Functions
    # ============================================================
    
    def _wait_for_endpoint(self, url: str, timeout: int, interval: int = 5) -> bool:
        """Wait for HTTP endpoint to be ready"""
        start = time.time()
        while time.time() - start < timeout:
            try:
                resp = self._http_client.get(url)
                if resp.status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(interval)
        return False
    
    def start_vllm(self) -> bool:
        """Start vLLM container"""
        cfg = self.config
        
        if self._container_running(cfg.vllm_container):
            return True
        
        # Remove existing stopped container
        self.remove_container(cfg.vllm_container)
        
        # Start container
        import os
        hf_cache = os.environ.get("HF_CACHE", os.path.expanduser("~/.cache/huggingface"))
        
        result = self._run_docker(
            "run", "-d", "--gpus", "all",
            "-v", f"{hf_cache}:/root/.cache/huggingface",
            "-p", f"{cfg.vllm_port}:8000",
            "--ipc=host",
            "--name", cfg.vllm_container,
            "vllm/vllm-openai:latest",
            "--model", cfg.vllm_model,
            "--gpu-memory-utilization", str(cfg.vllm_gpu_memory),
            "--max-model-len", str(cfg.vllm_max_model_len),
            "--trust-remote-code",
        )
        
        if result.returncode != 0:
            return False
        
        # Wait for startup
        return self._wait_for_endpoint(
            f"http://localhost:{cfg.vllm_port}/v1/models",
            cfg.vllm_startup_timeout,
            cfg.health_check_interval,
        )
    
    def start_florence(self) -> bool:
        """Start Florence-2 container"""
        cfg = self.config
        
        if self._container_running(cfg.florence_container):
            return True
        
        # Remove existing stopped container
        self.remove_container(cfg.florence_container)
        
        # Start container
        import os
        hf_cache = os.environ.get("HF_CACHE", os.path.expanduser("~/.cache/huggingface"))
        
        result = self._run_docker(
            "run", "-d", "--gpus", "all",
            "-v", f"{hf_cache}:/root/.cache/huggingface",
            "-p", f"{cfg.florence_port}:5001",
            "--ipc=host",
            "--name", cfg.florence_container,
            cfg.florence_image,
        )
        
        if result.returncode != 0:
            return False
        
        # Wait for startup
        return self._wait_for_endpoint(
            f"http://localhost:{cfg.florence_port}/health",
            cfg.florence_startup_timeout,
            cfg.health_check_interval,
        )
    
    def start_all(self) -> bool:
        """Start all services (vLLM first, then Florence-2)"""
        # Stop any existing containers first
        self.stop_all()
        time.sleep(2)
        self.clean_all()
        
        # Start vLLM first (needs more GPU memory)
        if not self.start_vllm():
            return False
        
        # Then start Florence-2
        if not self.start_florence():
            return False
        
        return True
    
    def ensure_running(self) -> bool:
        """Ensure all services are running, start if needed"""
        status = self.status()
        
        # Check if vLLM needs to be started
        if status["vllm"].state != ServiceState.RUNNING:
            # Need to restart everything to ensure proper GPU memory allocation
            return self.start_all()
        
        # Check if Florence-2 needs to be started
        if status["florence"].state != ServiceState.RUNNING:
            return self.start_florence()
        
        return True
    
    # ============================================================
    # Utility
    # ============================================================
    
    def get_logs(self, service: str = "all", tail: int = 50) -> Dict[str, str]:
        """Get container logs"""
        logs = {}
        
        if service in ("vllm", "all"):
            result = self._run_docker("logs", "--tail", str(tail), self.config.vllm_container)
            logs["vllm"] = result.stdout + result.stderr
        
        if service in ("florence", "all"):
            result = self._run_docker("logs", "--tail", str(tail), self.config.florence_container)
            logs["florence"] = result.stdout + result.stderr
        
        return logs
    
    def get_gpu_usage(self) -> Optional[Dict[str, Any]]:
        """Get GPU memory usage"""
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(",")
                used = int(parts[0].strip())
                total = int(parts[1].strip())
                return {
                    "used_mib": used,
                    "total_mib": total,
                    "used_gb": round(used / 1024, 2),
                    "total_gb": round(total / 1024, 2),
                    "percent": round(used / total * 100, 1),
                }
        except Exception:
            pass
        return None
    
    def print_status(self):
        """Print formatted status"""
        status = self.status()
        gpu = self.get_gpu_usage()
        
        print()
        print("╔══════════════════════════════════════════════════════════╗")
        print("║           duo-talk Docker Services Status                ║")
        print("╠══════════════════════════════════════════════════════════╣")
        
        for name, s in status.items():
            state_str = {
                ServiceState.RUNNING: "● Running",
                ServiceState.STARTING: "◐ Starting",
                ServiceState.STOPPED: "○ Stopped",
                ServiceState.ERROR: "✖ Error",
            }.get(s.state, "? Unknown")
            
            color = {
                ServiceState.RUNNING: "\033[92m",  # Green
                ServiceState.STARTING: "\033[93m",  # Yellow
                ServiceState.STOPPED: "\033[91m",  # Red
                ServiceState.ERROR: "\033[91m",  # Red
            }.get(s.state, "")
            reset = "\033[0m"
            
            port_str = f"(port {s.port})" if s.port else ""
            print(f"║  {name:12} {color}{state_str:12}{reset} {port_str:20} ║")
        
        print("╠══════════════════════════════════════════════════════════╣")
        
        if gpu:
            print(f"║  GPU Memory: {gpu['used_mib']}MiB / {gpu['total_mib']}MiB ({gpu['percent']}%)              ║")
        
        print("╚══════════════════════════════════════════════════════════╝")
        print()
    
    def close(self):
        """Close HTTP client"""
        self._http_client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ============================================================
# CLI
# ============================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="duo-talk Docker Service Manager")
    parser.add_argument("command", choices=["start", "stop", "restart", "status", "clean", "ensure"],
                       help="Command to execute")
    parser.add_argument("--service", choices=["vllm", "florence", "all"], default="all",
                       help="Service to operate on (default: all)")
    
    args = parser.parse_args()
    
    with DockerServiceManager() as manager:
        if args.command == "status":
            manager.print_status()
        
        elif args.command == "start":
            print("Starting services...")
            if manager.start_all():
                print("✅ All services started")
                manager.print_status()
            else:
                print("❌ Failed to start services")
                exit(1)
        
        elif args.command == "stop":
            print("Stopping services...")
            manager.stop_all()
            print("✅ Services stopped")
        
        elif args.command == "restart":
            print("Restarting services...")
            manager.stop_all()
            time.sleep(2)
            if manager.start_all():
                print("✅ Services restarted")
                manager.print_status()
            else:
                print("❌ Failed to restart services")
                exit(1)
        
        elif args.command == "clean":
            print("Cleaning up containers...")
            manager.clean_all()
            print("✅ Containers cleaned")
        
        elif args.command == "ensure":
            print("Ensuring services are running...")
            if manager.ensure_running():
                print("✅ All services running")
                manager.print_status()
            else:
                print("❌ Failed to ensure services")
                exit(1)


if __name__ == "__main__":
    main()
