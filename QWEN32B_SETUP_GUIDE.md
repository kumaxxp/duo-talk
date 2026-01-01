# Qwen 2.5 32B セットアップガイド - A5000サーバー

**目的**: A5000（24GB VRAM）でQwen 2.5 32Bを動作させ、duo-talkの会話品質を向上させる

---

## 問題背景

現在のmistral 7Bでは以下の問題が発生：
- **初耳問題**: 自分で言ったことを忘れる
- **設定破壊**: 姉妹が別居しているかのような表現
- **指示無視**: 2文以内の制約を守らない

## 解決策

より大きなモデル（Qwen 2.5 32B）に切り替えることで、コンテキスト理解と指示遵守を改善する。

---

## Part 1: A5000サーバーのセットアップ

### 方法A: vLLM（推奨・高速）

```bash
# 1. vLLMインストール
pip install vllm

# 2. Qwen2.5 32B (AWQ量子化版) でサーバー起動
vllm serve Qwen/Qwen2.5-32B-Instruct-AWQ \
    --quantization awq \
    --dtype half \
    --gpu-memory-utilization 0.90 \
    --max-model-len 8192 \
    --host 0.0.0.0 \
    --port 8000

# メモリ不足の場合は14Bにフォールバック
vllm serve Qwen/Qwen2.5-14B-Instruct-AWQ \
    --quantization awq \
    --dtype half \
    --gpu-memory-utilization 0.90 \
    --max-model-len 8192 \
    --host 0.0.0.0 \
    --port 8000
```

### 方法B: Ollama（簡単）

```bash
# 1. Ollamaインストール（まだの場合）
curl -fsSL https://ollama.com/install.sh | sh

# 2. Qwen2.5 32Bをダウンロード
ollama pull qwen2.5:32b-instruct-q4_K_M

# 3. サーバー起動（外部アクセス許可）
OLLAMA_HOST=0.0.0.0 ollama serve

# メモリ不足の場合は14Bにフォールバック
ollama pull qwen2.5:14b-instruct
```

### 疎通確認

```bash
# A5000側でテスト
curl http://localhost:8000/v1/models    # vLLM
curl http://localhost:11434/api/tags     # Ollama

# クライアント側からテスト（A5000のIPを指定）
curl http://<A5000_IP>:8000/v1/models    # vLLM
curl http://<A5000_IP>:11434/api/tags    # Ollama
```

---

## Part 2: duo-talk（クライアント）の設定

### 1. .envファイルを編集

```bash
cd /home/owner/work/duo-talk
```

**vLLMの場合**:
```env
OPENAI_BASE_URL=http://<A5000_IP>:8000/v1
OPENAI_API_KEY=not-needed
OPENAI_MODEL=Qwen/Qwen2.5-32B-Instruct-AWQ
MAX_TURNS=8
TEMPERATURE=0.7
MAX_TOKENS=200
TIMEOUT=120
```

**Ollamaの場合**:
```env
OPENAI_BASE_URL=http://<A5000_IP>:11434/v1
OPENAI_API_KEY=not-needed
OPENAI_MODEL=qwen2.5:32b-instruct-q4_K_M
MAX_TURNS=8
TEMPERATURE=0.7
MAX_TOKENS=200
TIMEOUT=120
```

### 2. タイムアウト設定（変更済み）

`src/config.py` のデフォルトタイムアウトは60秒に設定されています。
大きなモデルで応答が遅い場合は、.envで`TIMEOUT=120`を設定してください。

---

## Part 3: テスト実行

### 1. 基本疎通テスト

```bash
cd /home/owner/work/duo-talk
source /home/owner/miniconda3/etc/profile.d/conda.sh
conda activate duo-talk

# LLM接続テスト
python -c "
from src.llm_client import get_llm_client
c = get_llm_client()
print('Model:', c.model)
print('Response:', c.call('You are helpful.', 'Say hello in Japanese'))
"
```

### 2. 対話テスト

```bash
python scripts/run_narration.py
```

または、トピックのみモード：
```python
from scripts.run_narration import NarrationPipeline

pipeline = NarrationPipeline()
result = pipeline.process_image(
    image_path=None,
    scene_description="お正月は何をします？",
    max_iterations=8,
    skip_vision=True,
)
```

### 3. 検証ポイント

| 項目 | 現状（mistral 7B） | 目標（Qwen 32B） |
|------|-------------------|-----------------|
| 初耳反応 | 頻発 | 0回 |
| 設定破壊 | 頻発 | 0回 |
| 2文以内遵守 | 約30% | 80%以上 |
| 8ターン完走 | 成功 | 成功 |
| 応答時間 | ~3秒 | ~5-10秒（許容範囲） |

---

## Part 4: メモリ不足時のフォールバック

### VRAM使用量の目安

| モデル | 量子化 | VRAM使用量 | A5000 24GB |
|--------|--------|------------|------------|
| Qwen2.5-32B | AWQ (4bit) | 18-20GB | ギリギリ |
| Qwen2.5-32B | Q4_K_M | 20-22GB | ギリギリ |
| Qwen2.5-14B | AWQ | 8-10GB | 余裕 |
| Qwen2.5-14B | FP16 | 28GB | 動かない |

### OOM（メモリ不足）が発生した場合

```bash
# 1. gpu-memory-utilizationを下げる
vllm serve Qwen/Qwen2.5-32B-Instruct-AWQ \
    --gpu-memory-utilization 0.85 \
    ...

# 2. max-model-lenを下げる
vllm serve Qwen/Qwen2.5-32B-Instruct-AWQ \
    --max-model-len 4096 \
    ...

# 3. それでもダメなら14Bにフォールバック
vllm serve Qwen/Qwen2.5-14B-Instruct-AWQ \
    --quantization awq \
    --dtype half \
    --gpu-memory-utilization 0.90 \
    --max-model-len 8192 \
    --host 0.0.0.0 \
    --port 8000
```

---

## Part 5: 期待される改善

### 改善前（mistral 7B）
```
Turn 1 あゆ: 「うちでは書道が盛んなんですよ」
Turn 3 あゆ: 「書道が盛んなんですね」 ← 自分の発言を忘れている（初耳反応）
```

### 改善後（Qwen 32B）
```
Turn 1 あゆ: 「うちでは書道が盛んなんですよ」
Turn 3 あゆ: 「さっき言った書道の話ですが、初詣で書き初めするのも良いですね」
          ← 自分の発言を覚えている
```

### ステートフル履歴の活用

duo-talkの新しい`call_with_history`機能により、会話履歴がLLMのメッセージ履歴として正確に渡されます：
- 相手の発言 → `user`ロール
- 自分の過去発言 → `assistant`ロール

これにより、大きなモデルはより正確にコンテキストを理解できます。

---

## トラブルシューティング

### vLLMが起動しない

```bash
# CUDAバージョン確認
nvidia-smi

# vLLMの依存関係を確認
pip install vllm --upgrade

# 詳細ログで起動
VLLM_LOGGING_LEVEL=DEBUG vllm serve ...
```

### 接続がタイムアウトする

```bash
# ファイアウォール確認
sudo ufw status
sudo ufw allow 8000/tcp

# ポートが開いているか確認
netstat -tlnp | grep 8000
```

### 応答が遅い

```bash
# タイムアウトを延長（.env）
TIMEOUT=180

# または、max-model-lenを下げて高速化
vllm serve ... --max-model-len 4096
```

---

## クイックスタートコマンド

### A5000サーバー側
```bash
# vLLMでQwen 32B起動
vllm serve Qwen/Qwen2.5-32B-Instruct-AWQ \
    --quantization awq --dtype half \
    --gpu-memory-utilization 0.90 \
    --max-model-len 8192 \
    --host 0.0.0.0 --port 8000
```

### クライアント側
```bash
# .env設定
echo "OPENAI_BASE_URL=http://<A5000_IP>:8000/v1" > .env
echo "OPENAI_API_KEY=not-needed" >> .env
echo "OPENAI_MODEL=Qwen/Qwen2.5-32B-Instruct-AWQ" >> .env
echo "TIMEOUT=120" >> .env

# テスト実行
cd /home/owner/work/duo-talk
source /home/owner/miniconda3/etc/profile.d/conda.sh
conda activate duo-talk
python scripts/run_narration.py
```

---

**最終更新**: 2026-01-01
**ステータス**: セットアップ準備完了
