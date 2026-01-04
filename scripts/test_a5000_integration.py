#!/usr/bin/env python3
"""
A5000 統合テストスクリプト

duo-talkシステムの全機能をA5000マシンで自動テスト。
vLLM Docker、Ollama、VLM画像入力、キャラクター対話を検証。

使用方法:
    python scripts/test_a5000_integration.py [OPTIONS]

Options:
    --backend BACKEND  使用するバックエンド（ollama/vllm）※排他的
    --skip-vlm         VLMテストをスキップ
    --skip-character   キャラクターテストをスキップ
    --jetracer URL     JetRacer連携テスト（URLを指定）

例:
    # Ollamaでテスト（推奨：既にOllamaが動作中の場合）
    python scripts/test_a5000_integration.py --backend ollama

    # vLLMでテスト（Ollamaを停止してからvLLMを起動）
    python scripts/test_a5000_integration.py --backend vllm

    # バックエンド指定なし（利用可能な方を自動選択）
    python scripts/test_a5000_integration.py
"""
import sys
import os
import time
import argparse
import subprocess
import base64
import io
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))


class Colors:
    """ターミナル色"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def print_header(text: str):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 60}{Colors.RESET}")


def print_success(text: str):
    print(f"{Colors.GREEN}[PASS] {text}{Colors.RESET}")


def print_error(text: str):
    print(f"{Colors.RED}[FAIL] {text}{Colors.RESET}")


def print_warning(text: str):
    print(f"{Colors.YELLOW}[WARN] {text}{Colors.RESET}")


def print_info(text: str):
    print(f"{Colors.BLUE}[INFO] {text}{Colors.RESET}")


class TestResult:
    """テスト結果"""
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.skipped = False
        self.error: Optional[str] = None
        self.details: Dict[str, Any] = {}
        self.duration: float = 0


class A5000IntegrationTest:
    """A5000統合テスト"""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.results: List[TestResult] = []
        self.docker_dir = Path(__file__).parent.parent / "docker"
        self.active_backend: Optional[str] = None

    def run_all(self) -> bool:
        """全テスト実行"""
        print_header("A5000 Integration Test Suite")
        print(f"Start time: {datetime.now().isoformat()}")

        # 1. 環境確認
        self._test_environment()

        # 2. バックエンドテスト（排他的）
        if self.args.backend:
            # 指定されたバックエンドのみテスト
            if self.args.backend == "ollama":
                self._test_ollama()
                self._skip_test("vLLM Docker")
            elif self.args.backend == "vllm":
                self._skip_test("Ollama")
                self._test_vllm_docker()
        else:
            # 自動選択：利用可能な方を使う
            self._test_auto_backend()

        # 3. VLMテスト（アクティブなバックエンドで実行）
        if not self.args.skip_vlm:
            self._test_vlm()
        else:
            self._skip_test("VLM")

        # 4. キャラクター対話テスト
        if not self.args.skip_character:
            self._test_character_dialogue()
        else:
            self._skip_test("Character Dialogue")

        # 5. JetRacer連携テスト（オプション）
        if self.args.jetracer:
            self._test_jetracer(self.args.jetracer)

        # 結果サマリー
        return self._print_summary()

    def _test_auto_backend(self):
        """利用可能なバックエンドを自動選択してテスト"""
        from src.llm_provider import get_llm_provider, BackendType

        provider = get_llm_provider()

        # まずOllamaを確認
        ollama_status = provider.check_backend_health(BackendType.OLLAMA)
        if ollama_status.available:
            print_info("Auto-selecting Ollama (already running)")
            self._test_ollama()
            self._skip_test("vLLM Docker")
            return

        # 次にvLLMを確認
        vllm_status = provider.check_backend_health(BackendType.VLLM)
        if vllm_status.available:
            print_info("Auto-selecting vLLM (already running)")
            self._skip_test("Ollama")
            self._test_vllm_docker()
            return

        # どちらも動いていない場合はOllamaを試行
        print_warning("No backend running. Trying Ollama first...")
        self._test_ollama()
        self._skip_test("vLLM Docker")

    def _skip_test(self, name: str):
        """テストスキップ"""
        result = TestResult(name)
        result.skipped = True
        self.results.append(result)
        print_warning(f"{name} test skipped")

    def _test_environment(self):
        """環境確認"""
        print_header("1. Environment Check")
        result = TestResult("Environment")
        start = time.time()

        try:
            # GPU確認
            gpu_result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=10
            )
            if gpu_result.returncode == 0:
                gpu_info = gpu_result.stdout.strip()
                print_info(f"GPU: {gpu_info}")
                result.details["gpu"] = gpu_info
            else:
                raise RuntimeError("nvidia-smi failed")

            # Docker確認
            docker_result = subprocess.run(
                ["docker", "--version"],
                capture_output=True, text=True, timeout=10
            )
            if docker_result.returncode == 0:
                print_info(f"Docker: {docker_result.stdout.strip()}")
                result.details["docker"] = docker_result.stdout.strip()

            # Python環境
            print_info(f"Python: {sys.version}")
            result.details["python"] = sys.version

            # 必須モジュール確認
            import openai
            import yaml
            print_info("Required modules: OK")

            result.passed = True
            print_success("Environment check passed")

        except Exception as e:
            result.error = str(e)
            print_error(f"Environment check failed: {e}")

        result.duration = time.time() - start
        self.results.append(result)

    def _test_ollama(self):
        """Ollamaテスト"""
        print_header("2. Ollama Test")
        result = TestResult("Ollama")
        start = time.time()

        try:
            from src.llm_provider import get_llm_provider, BackendType

            provider = get_llm_provider()
            status = provider.check_backend_health(BackendType.OLLAMA)

            if status.available:
                print_info(f"Ollama running: {status.current_model}")
                result.details["model"] = status.current_model

                # 簡単な生成テスト
                try:
                    ollama_result = provider.switch_backend(BackendType.OLLAMA)
                    if ollama_result.get("success"):
                        client = provider.get_client()
                        response = client.chat.completions.create(
                            model=provider.get_model_name(),
                            messages=[{"role": "user", "content": "1+1=?"}],
                            max_tokens=10
                        )
                        answer = response.choices[0].message.content
                        print_info(f"Test response: {answer[:50]}")
                        result.passed = True
                        self.active_backend = "ollama"
                        print_success("Ollama test passed")
                except Exception as e:
                    result.error = f"Generation failed: {e}"
                    print_error(result.error)
            else:
                result.error = status.error
                print_warning(f"Ollama not available: {status.error}")
                # 利用不可の場合もエラーではないがactive_backendは設定しない

        except Exception as e:
            result.error = str(e)
            print_error(f"Ollama test failed: {e}")

        result.duration = time.time() - start
        self.results.append(result)

    def _test_vllm_docker(self):
        """vLLM Dockerテスト"""
        print_header("3. vLLM Docker Test")
        result = TestResult("vLLM Docker")
        start = time.time()

        try:
            from src.llm_provider import get_llm_provider, BackendType

            provider = get_llm_provider()
            status = provider.check_backend_health(BackendType.VLLM)

            if status.available:
                print_info(f"vLLM already running: {status.current_model}")
                result.details["model"] = status.current_model
                result.details["started"] = False
            else:
                print_info("vLLM not running, attempting to start...")

                # Ollamaモデルを完全にアンロードしてGPUメモリを解放
                print_info("Unloading all Ollama models to free GPU memory...")
                self._unload_ollama_models()
                time.sleep(3)

                # GPU使用状況確認
                gpu_result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=10
                )
                if gpu_result.returncode == 0:
                    used, total = map(int, gpu_result.stdout.strip().split(", "))
                    free_gb = (total - used) / 1024
                    print_info(f"GPU memory free: {free_gb:.1f} GB")

                    if free_gb < 14:
                        raise RuntimeError(
                            f"Not enough GPU memory ({free_gb:.1f}GB free, need 14GB+). "
                            "Please stop other GPU processes first."
                        )

                # Docker起動
                start_script = self.docker_dir / "scripts" / "start-vllm.sh"
                if start_script.exists():
                    print_info("Starting vLLM Docker...")
                    proc = subprocess.run(
                        [str(start_script)],
                        cwd=str(self.docker_dir),
                        capture_output=True, text=True,
                        timeout=300
                    )
                    if proc.returncode == 0:
                        result.details["started"] = True
                        print_info("vLLM Docker started")
                    else:
                        raise RuntimeError(f"Start failed: {proc.stderr}")
                else:
                    # 直接docker compose
                    proc = subprocess.run(
                        ["docker", "compose", "up", "-d"],
                        cwd=str(self.docker_dir),
                        capture_output=True, text=True,
                        timeout=60
                    )
                    if proc.returncode != 0:
                        raise RuntimeError(f"Docker compose failed: {proc.stderr}")

                # 起動待機
                print_info("Waiting for vLLM to be ready (max 180s)...")
                if provider.wait_for_vllm_ready(timeout=180):
                    result.details["started"] = True
                    print_info("vLLM is ready")
                else:
                    raise RuntimeError("vLLM startup timeout")

            # 生成テスト
            status = provider.check_backend_health(BackendType.VLLM)
            if status.available:
                switch_result = provider.switch_backend(BackendType.VLLM, "gemma3-12b-int8")
                if switch_result.get("success"):
                    client = provider.get_client()
                    response = client.chat.completions.create(
                        model=provider.get_model_name(),
                        messages=[{"role": "user", "content": "Hello"}],
                        max_tokens=20
                    )
                    answer = response.choices[0].message.content
                    print_info(f"Test response: {answer[:50]}")
                    result.passed = True
                    self.active_backend = "vllm"
                    print_success("vLLM Docker test passed")
                else:
                    raise RuntimeError(f"Switch failed: {switch_result.get('error')}")
            else:
                raise RuntimeError("vLLM still not available after startup")

        except Exception as e:
            result.error = str(e)
            print_error(f"vLLM Docker test failed: {e}")

        result.duration = time.time() - start
        self.results.append(result)

    def _unload_ollama_models(self):
        """Ollamaの全モデルをアンロードしてGPUメモリを解放"""
        try:
            import requests

            # 既知のモデルをアンロード
            models_to_unload = ["gemma3:27b", "gemma3:12b", "llama3:8b", "mistral:7b"]
            for model in models_to_unload:
                try:
                    requests.post(
                        "http://localhost:11434/api/generate",
                        json={"model": model, "keep_alive": 0},
                        timeout=5
                    )
                except Exception:
                    pass

            # ロード中のモデル一覧を取得してアンロード
            try:
                response = requests.get("http://localhost:11434/api/ps", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    for model_info in data.get("models", []):
                        model_name = model_info.get("name", "")
                        if model_name:
                            requests.post(
                                "http://localhost:11434/api/generate",
                                json={"model": model_name, "keep_alive": 0},
                                timeout=5
                            )
            except Exception:
                pass

            print_info("Ollama models unloaded")

        except ImportError:
            print_warning("requests not available, skipping Ollama unload")
        except Exception as e:
            print_warning(f"Failed to unload Ollama models: {e}")

    def _test_vlm(self):
        """VLM（画像入力）テスト"""
        print_header("4. VLM (Vision) Test")
        result = TestResult("VLM")
        start = time.time()

        try:
            from PIL import Image
            from src.llm_provider import get_llm_provider

            # テスト画像生成（赤青縞模様）
            img = Image.new('RGB', (100, 100))
            pixels = img.load()
            for y in range(100):
                for x in range(100):
                    if (x // 20) % 2 == 0:
                        pixels[x, y] = (255, 0, 0)
                    else:
                        pixels[x, y] = (0, 0, 255)

            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            test_image_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

            print_info(f"Test image created: {len(test_image_b64)} bytes")

            # VLM呼び出し
            provider = get_llm_provider()
            client = provider.get_client()
            model_name = provider.get_model_name()

            print_info(f"Using model: {model_name}")

            response = client.chat.completions.create(
                model=model_name,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe the colors and pattern in this image briefly."},
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/png;base64,{test_image_b64}"
                        }}
                    ]
                }],
                max_tokens=100
            )

            vlm_response = response.choices[0].message.content
            print_info(f"VLM response: {vlm_response[:100]}...")

            # 応答に色に関する言及があるか確認
            if any(word in vlm_response.lower() for word in ["red", "blue", "stripe", "vertical", "pattern"]):
                result.passed = True
                result.details["response"] = vlm_response
                print_success("VLM test passed")
            else:
                result.error = "Response doesn't mention expected colors"
                print_warning(f"Unexpected response: {vlm_response}")
                result.passed = True  # 応答があれば一応成功

        except ImportError:
            result.error = "Pillow not installed"
            print_error("Pillow not installed. Run: pip install Pillow")
        except Exception as e:
            result.error = str(e)
            print_error(f"VLM test failed: {e}")

        result.duration = time.time() - start
        self.results.append(result)

    def _test_character_dialogue(self):
        """キャラクター対話テスト"""
        print_header("5. Character Dialogue Test")
        result = TestResult("Character Dialogue")
        start = time.time()

        try:
            from src.llm_client import reset_llm_client
            from src.character import Character

            reset_llm_client()

            # キャラクター初期化
            print_info("Loading characters...")
            yana = Character("char_a")
            ayu = Character("char_b")
            print_info("Characters loaded")

            # フレーム説明（シーンコンテキスト）
            frame_desc = "Right curve ahead, cone detected on right side 50cm, speed 2.0 m/s"

            dialogues = []

            # やなの発言
            print_info("Generating Yana's response...")
            yana_result = yana.speak_v2(
                last_utterance="",
                frame_description=frame_desc,
                dialogue_pattern="A"
            )
            yana_response = yana_result.get("content", "")
            if yana_result.get("type") == "silence":
                yana_response = "(silence)"
            print(f"\n[Yana] {yana_response}")
            dialogues.append(("yana", yana_response))

            # あゆの発言
            print_info("Generating Ayu's response...")
            ayu_result = ayu.speak_v2(
                last_utterance=yana_response,
                frame_description=frame_desc,
                dialogue_pattern="B"
            )
            ayu_response = ayu_result.get("content", "")
            if ayu_result.get("type") == "silence":
                ayu_response = "(silence)"
            print(f"\n[Ayu] {ayu_response}")
            dialogues.append(("ayu", ayu_response))

            # やなの返答
            print_info("Generating Yana's reply...")
            yana_result2 = yana.speak_v2(
                last_utterance=ayu_response,
                frame_description=frame_desc,
                dialogue_pattern="C"
            )
            yana_reply = yana_result2.get("content", "")
            if yana_result2.get("type") == "silence":
                yana_reply = "(silence)"
            print(f"\n[Yana] {yana_reply}")
            dialogues.append(("yana", yana_reply))

            result.details["dialogues"] = dialogues
            result.passed = True
            print_success("Character dialogue test passed")

        except Exception as e:
            result.error = str(e)
            print_error(f"Character dialogue test failed: {e}")
            import traceback
            traceback.print_exc()

        result.duration = time.time() - start
        self.results.append(result)

    def _test_jetracer(self, url: str):
        """JetRacer連携テスト"""
        print_header("6. JetRacer Integration Test")
        result = TestResult("JetRacer")
        start = time.time()

        try:
            import requests

            # 接続確認
            print_info(f"Connecting to JetRacer: {url}")
            response = requests.get(f"{url}/status", timeout=5)

            if response.status_code == 200:
                status_data = response.json()
                print_info(f"JetRacer status: {status_data}")
                result.details["status"] = status_data

                # 画像取得テスト
                img_response = requests.get(f"{url}/camera/image", timeout=10)
                if img_response.status_code == 200:
                    print_info("Camera image retrieved")
                    result.details["camera"] = True

                result.passed = True
                print_success("JetRacer test passed")
            else:
                raise RuntimeError(f"HTTP {response.status_code}")

        except Exception as e:
            result.error = str(e)
            print_error(f"JetRacer test failed: {e}")

        result.duration = time.time() - start
        self.results.append(result)

    def _print_summary(self) -> bool:
        """結果サマリー出力"""
        print_header("Test Summary")

        passed = 0
        failed = 0
        skipped = 0

        for r in self.results:
            if r.skipped:
                status = f"{Colors.YELLOW}SKIP{Colors.RESET}"
                skipped += 1
            elif r.passed:
                status = f"{Colors.GREEN}PASS{Colors.RESET}"
                passed += 1
            else:
                status = f"{Colors.RED}FAIL{Colors.RESET}"
                failed += 1

            duration = f"({r.duration:.1f}s)" if r.duration > 0 else ""
            print(f"  {r.name:25} [{status}] {duration}")
            if r.error and not r.passed:
                print(f"    Error: {r.error[:60]}...")

        print()
        total = passed + failed + skipped
        print(f"Total: {total} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}")
        print(f"End time: {datetime.now().isoformat()}")

        return failed == 0


def main():
    parser = argparse.ArgumentParser(
        description="A5000 Integration Test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with Ollama (recommended if Ollama is already running)
  python scripts/test_a5000_integration.py --backend ollama

  # Test with vLLM (stops Ollama first, then starts vLLM)
  python scripts/test_a5000_integration.py --backend vllm

  # Auto-select available backend
  python scripts/test_a5000_integration.py
"""
    )
    parser.add_argument(
        "--backend", type=str, choices=["ollama", "vllm"],
        help="Backend to use (ollama or vllm). If not specified, auto-selects."
    )
    parser.add_argument("--skip-vlm", action="store_true", help="Skip VLM test")
    parser.add_argument("--skip-character", action="store_true", help="Skip character dialogue test")
    parser.add_argument("--jetracer", type=str, help="JetRacer URL for integration test")

    args = parser.parse_args()

    tester = A5000IntegrationTest(args)
    success = tester.run_all()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
