import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - tests may run without dotenv installed
    def load_dotenv(*args, **kwargs):  # type: ignore
        return None


# ---------- Utility: JSONL logging ----------
RUNS_DIR = Path("runs")
RUNS_FILE = RUNS_DIR / "duo_runs.jsonl"


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _ensure_runs_dir() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def _write_event(event: dict) -> None:
    _ensure_runs_dir()
    event = {"ts": _utc_now_iso(), **event}
    with RUNS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# ---------- Public API helpers ----------


_SENT_SPLIT_RE = re.compile(r"[。．.!?！？]+")


def too_many_sentences(text: str, limit: int = 5) -> bool:
    """Return True if sentence count exceeds limit.

    Heuristic: split on common Japanese and Latin sentence enders.
    Empty segments are ignored.
    """
    if not text:
        return False
    parts = [p for p in _SENT_SPLIT_RE.split(text) if p.strip()]
    return len(parts) > limit


_AIZUCHI_WORDS = [
    # Common short interjections (Japanese)
    "うん",
    "へぇ",
    "へえ",
    "なるほど",
    "そうそう",
    "ふむ",
    "ええ",
    "はい",
    "そっか",
    "そうか",
    "たしかに",
    "なる",
]


def _count_aizuchi(text: str) -> int:
    if not text:
        return 0
    count = 0
    # Count as standalone words or separated by punctuation/whitespace
    for w in _AIZUCHI_WORDS:
        # word boundary heuristic for Japanese: allow start/end or punctuation/space around
        pattern = rf"(?:(?<=^)|(?<=[\s、。.!?！？])){re.escape(w)}(?:(?=$)|(?=[\s、。.!?！？]))"
        count += len(re.findall(pattern, text))
    return count


def too_many_aizuchi(text: str, limit: int = 1) -> bool:
    return _count_aizuchi(text) > limit


def is_loop(prev: str, curr: str) -> bool:
    """Naive loop detection: identical after normalization or extremely similar.

    This is intentionally simple for MVP. It trims whitespace and collapses spaces.
    """
    import difflib

    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s or "").strip()

    a, b = _norm(prev), _norm(curr)
    if not a or not b:
        return False
    if a == b:
        return True
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    return ratio >= 0.98


def _hard_trim(text: str, sent_limit: int = 5, aizuchi_limit: int = 1) -> str:
    """Last‑resort enforcement: trim to N sentences and cap aizuchi occurrences.

    This is used only if the model keeps violating constraints after retries.
    """
    raw = (text or "").strip()
    if not raw:
        return raw
    # Limit sentences
    parts = [p.strip() for p in _SENT_SPLIT_RE.split(raw) if p.strip()]
    trimmed = "。".join(parts[: max(1, sent_limit)]).strip()
    if trimmed and trimmed[-1] not in "。．.!?！？】)）】]」』\n":
        trimmed += "。"
    # Cap aizuchi occurrences across all words
    alt = "|".join(sorted(map(re.escape, _AIZUCHI_WORDS), key=len, reverse=True))
    boundary = r"(?:(?<=^)|(?<=[\s、。.!?！？]))"
    pattern = re.compile(boundary + f"(?:{alt})" + r"(?:(?=$)|(?=[\s、。.!?！？]))")
    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        count += 1
        return m.group(0) if count <= max(0, aizuchi_limit) else ""

    trimmed = pattern.sub(repl, trimmed)
    return trimmed


# Public: strict, formatting-preserving hard enforcement (exported for Step2)
def hard_enforce(text: str, sent_limit: int = 5, aizuchi_limit: int = 1) -> str:
    return _hard_trim(text, sent_limit=sent_limit, aizuchi_limit=aizuchi_limit)


# Public: simple sanitizer to reduce risky tokens or leaked notes
_SANITIZE_PATTERNS = [
    # Remove accidental printed direction notes like 「［演出ノート］…」
    (re.compile(r"\u3014?\[?演出ノート\]?\u3015?:?.*$", re.MULTILINE), ""),
]


def sanitize(text: str) -> str:
    s = text or ""
    for pat, repl in _SANITIZE_PATTERNS:
        s = pat.sub(repl, s)
    return s.strip()


# ---------- LLM call wrapper ----------


@dataclass
class LLMConfig:
    base_url: Optional[str]
    model: str
    api_key: Optional[str]
    temperature: float = 0.7
    max_tokens: int = 400


def _load_llm_config(model: Optional[str] = None, temperature: float = 0.7, max_tokens: int = 400) -> LLMConfig:
    # Load .env once
    load_dotenv(override=False)
    base_url = os.getenv("OPENAI_BASE_URL")
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_TOKEN") or os.getenv("LMSTUDIO_API_KEY") or "sk-"
    model_name = model or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
    return LLMConfig(
        base_url=base_url,
        model=model_name,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def call(model: str, system: str, user: str, temperature: float = 0.7, max_tokens: int = 400) -> str:
    """Call an OpenAI-compatible Chat Completions API and return the text.

    Errors are not swallowed: the caller can handle retries.
    """
    from openai import OpenAI

    cfg = _load_llm_config(model=model, temperature=temperature, max_tokens=max_tokens)
    client = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)

    _write_event(
        {
            "event": "llm_call",
            "provider": "openai-compatible",
            "model": cfg.model,
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            "system_len": len(system or ""),
            "user_len": len(user or ""),
        }
    )

    resp = client.chat.completions.create(
        model=cfg.model,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    text = (resp.choices[0].message.content or "").strip()
    _write_event(
        {
            "event": "llm_response",
            "model": cfg.model,
            "content_len": len(text),
        }
    )
    return text


def enforce(
    text: str,
    system: str,
    user: str,
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 400,
    tries: int = 2,
) -> str:
    """Enforce output constraints: <=5 sentences, <=1 aizuchi.

    If the initial text violates constraints, try up to `tries` regenerations
    with augmented instruction to satisfy constraints. Always exits after `tries`.
    """
    def valid(t: str) -> bool:
        return not too_many_sentences(t) and not too_many_aizuchi(t)

    candidate = (text or "").strip()
    attempts = 0
    if not candidate:
        # First generation
        candidate = call(model=model, system=system, user=user, temperature=temperature, max_tokens=max_tokens)
        attempts += 1

    while attempts <= tries and not valid(candidate):
        hint = (
            "厳守事項:\n"
            "- 最大5文。6文目は出力しない。\n"
            "- 合いの手（短い相槌）は最大1回。\n"
            "- 箇条書き・番号・前置き・自己言及は禁止。返答のみ。\n"
            "- 日本語で簡潔に自然に。専門用語は噛み砕く。\n"
        )
        augmented_user = f"{hint}\n\n前の相手発言:\n{user}\n\n制約を満たす新しい応答:"
        candidate = call(
            model=model,
            system=system,
            user=augmented_user,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        attempts += 1

    if not valid(candidate):
        before_sent = len([p for p in _SENT_SPLIT_RE.split(candidate) if p.strip()])
        before_ai = _count_aizuchi(candidate)
        candidate = _hard_trim(candidate)
        after_sent = len([p for p in _SENT_SPLIT_RE.split(candidate) if p.strip()])
        after_ai = _count_aizuchi(candidate)
        _write_event(
            {
                "event": "enforced_trim",
                "before_sentences": before_sent,
                "after_sentences": after_sent,
                "before_aizuchi": before_ai,
                "after_aizuchi": after_ai,
            }
        )

    return candidate


# ---------- Main duo chat loop (MVP) ----------


def _load_persona(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _speaker(
    system_path: Path,
    name: str,
    partner_last: Optional[str],
    *,
    model: str,
    temperature: float,
    max_tokens: int,
    topic: Optional[str] = None,
) -> str:
    system = _load_persona(system_path)
    constraints = (
        "絶対条件: 最大5文、合いの手は最大1回。箇条書きや前置きは禁止。返答のみを日本語で簡潔に。"
    )
    if partner_last:
        if topic:
            user = (
                f"{constraints}\n"
                f"会話のトピック: {topic}\n"
                f"相手の直前の発言: \n{partner_last}\n\n"
                "このトピックの範囲で自然に返答してください。"
            )
        else:
            user = f"{constraints}\n相手の直前の発言: \n{partner_last}\n\nこれに応じて自然に返答してください。"
    else:
        if topic:
            user = (
                f"{constraints}\n"
                f"会話のトピック: {topic}\n"
                "トピックに軽く触れつつ自己紹介して会話を始めてください。"
            )
        else:
            user = f"{constraints}\n軽く自己紹介して会話を始めてください。"

    # First attempt
    try:
        raw = call(
            model=model,
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:
        _write_event({"event": "error", "stage": "call_first", "speaker": name, "message": str(e)})
        raise

    # Enforce constraints with up to 2 retries
    try:
        fixed = enforce(
            raw,
            system=system,
            user=user,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tries=2,
        )
    except Exception as e:
        _write_event({"event": "error", "stage": "enforce", "speaker": name, "message": str(e)})
        raise

    _write_event({"event": "speak", "speaker": name, "text": fixed})
    return fixed


def run_duo(
    max_turns: int = 6,
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    topic: Optional[str] = None,
) -> None:
    a_sys = Path("persona/char_a.system.txt")
    b_sys = Path("persona/char_b.system.txt")
    if not a_sys.exists() or not b_sys.exists():
        raise FileNotFoundError("persona system files not found under persona/")

    turn = 0
    last_a: Optional[str] = None
    last_b: Optional[str] = None

    # Resolve runtime parameters from args/env
    load_dotenv(override=False)
    # sanitize model name from env (strip inline comments/extra spaces)
    def _sanitize_model_name(name: str) -> str:
        name = name.strip()
        # cut off inline comment markers
        if "#" in name:
            name = name.split("#", 1)[0].strip()
        return name

    env_model = os.getenv("OPENAI_MODEL")
    resolved_model = _sanitize_model_name(env_model) if (model is None and env_model) else (model or "gpt-4o-mini")
    resolved_temperature = float(temperature if temperature is not None else os.getenv("OPENAI_TEMPERATURE", "0.7"))
    resolved_max_tokens = int(max_tokens if max_tokens is not None else os.getenv("OPENAI_MAX_TOKENS", "400"))
    resolved_topic = topic or os.getenv("TOPIC") or None

    # Alternate A -> B -> A ...
    while turn < max_turns:
        if turn % 2 == 0:
            # A speaks using B's last line
            text_a = _speaker(
                a_sys,
                name="A",
                partner_last=last_b,
                model=resolved_model,
                temperature=resolved_temperature,
                max_tokens=resolved_max_tokens,
                topic=resolved_topic,
            )
            if last_a is not None and is_loop(last_a, text_a):
                _write_event({"event": "loop_detected", "speaker": "A"})
            print(f"A: {text_a}")
            last_a = text_a
        else:
            # B speaks using A's last line
            text_b = _speaker(
                b_sys,
                name="B",
                partner_last=last_a,
                model=resolved_model,
                temperature=resolved_temperature,
                max_tokens=resolved_max_tokens,
                topic=resolved_topic,
            )
            if last_b is not None and is_loop(last_b, text_b):
                _write_event({"event": "loop_detected", "speaker": "B"})
            print(f"B: {text_b}")
            last_b = text_b
        turn += 1


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Duo Talk MVP: two AI characters alternate conversation")
    p.add_argument("--max-turns", type=int, default=int(os.getenv("MAX_TURNS", "6")), help="Maximum total turns")
    # Let run_duo resolve env defaults after .env is loaded
    p.add_argument("--model", type=str, default=None, help="Model name override (defaults to OPENAI_MODEL)")
    p.add_argument("--temperature", type=float, default=None, help="Sampling temperature (defaults to OPENAI_TEMPERATURE)")
    p.add_argument("--max-tokens", type=int, default=None, help="Max tokens (defaults to OPENAI_MAX_TOKENS)")
    p.add_argument("--topic", type=str, default=None, help="Conversation topic / theme (defaults to TOPIC)")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    # Ensure .env is loaded before parsing env-aware defaults downstream
    load_dotenv(override=False)
    args = _parse_args(argv or [])
    _write_event({
        "event": "run_start",
        "max_turns": args.max_turns,
        "model": args.model,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "topic": args.topic,
    })
    try:
        run_duo(
            max_turns=args.max_turns,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            topic=args.topic,
        )
    except KeyboardInterrupt:
        _write_event({"event": "interrupted"})
        return 130
    except Exception as e:
        _write_event({"event": "fatal", "error": str(e)})
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        _write_event({"event": "run_end"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
