import argparse
import os
from pathlib import Path
from typing import Optional, Dict, Any

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    def load_dotenv(*args, **kwargs):  # type: ignore
        return None

from duo_chat_mvp import (
    call,
    enforce,
    hard_enforce,
    sanitize,
    is_loop,
    too_many_sentences,
    too_many_aizuchi,
)
from duo_chat_mvp import _write_event  # reuse logging helper


DEFAULT_POLICY = {
    "beats": {
        "default": "BANter",
        "rules": [
            {"every": 3, "beat": "PIVOT"},
            {"from_turn": 6, "beat": "PAYOFF"},
        ],
    },
    "cuts": {
        "default": None,
        "rules": [
            {"last_turn": True, "cut": "TAG"},
        ],
    },
}


def load_policy(path: str = "beats/beat_policy.yaml") -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return DEFAULT_POLICY
    try:
        try:
            import yaml  # type: ignore
        except Exception:
            return DEFAULT_POLICY
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        # merge shallowly over defaults
        policy = DEFAULT_POLICY.copy()
        for k in ("beats", "cuts"):
            if k in data and isinstance(data[k], dict):
                merged = policy[k].copy()
                merged.update({kk: data[k].get(kk, merged.get(kk)) for kk in data[k].keys()})
                policy[k] = merged
        return policy
    except Exception:
        # Fallback safely
        return DEFAULT_POLICY


def pick_beat(turn: int, policy: Dict[str, Any] | None = None) -> str:
    pol = policy or load_policy()
    beats = pol.get("beats", {})
    current = beats.get("default", "BANter")
    for rule in beats.get("rules", []):
        if "every" in rule and rule.get("every"):
            every = int(rule["every"]) or 0
            if every > 0 and turn % every == 0:
                current = rule.get("beat", current)
        if "from_turn" in rule and rule.get("from_turn") is not None:
            if turn >= int(rule["from_turn"]):
                current = rule.get("beat", current)
    return current


def pick_cut(turn: int, max_turns: int = 8, policy: Dict[str, Any] | None = None) -> Optional[str]:
    pol = policy or load_policy()
    cuts = pol.get("cuts", {})
    current = cuts.get("default")
    for rule in cuts.get("rules", []):
        if rule.get("last_turn") and turn == max_turns:
            current = rule.get("cut", current)
        if "from_turn" in rule and rule.get("from_turn") is not None:
            if turn >= int(rule["from_turn"]):
                current = rule.get("cut", current)
    return current


_FINISH_PAT = (
    r"TAG|CUT|CLIFF|ここで切る|ここで一旦切る|締めよう|締める|そろそろ終わろ"
)


def need_finish(text: str) -> bool:
    import re

    if not text:
        return False
    return re.search(_FINISH_PAT, text, flags=re.IGNORECASE) is not None


def _sanitize_model_name(name: str) -> str:
    name = name.strip()
    if "#" in name:
        name = name.split("#", 1)[0].strip()
    return name


def _compose_user(partner_last: Optional[str], topic: Optional[str], beat: str) -> str:
    constraints = (
        "絶対条件: 最大5文、合いの手は最大1回。箇条書きや前置きは禁止。返答のみを日本語で簡潔に。"
    )
    base = []
    base.append(constraints)
    if topic:
        base.append(f"会話のトピック: {topic}")
    if partner_last:
        base.append(f"相手の直前の発言:\n{partner_last}")
        base.append("これに応じて自然に返答してください。")
    else:
        base.append("トピックに軽く触れつつ自己紹介して会話を始めてください。")
    # Director's note (should not leak)
    base.append(f"［演出ノート］現在: {beat}。露骨な演出語は避け、自然に反映。ノートは台詞に出さない。")
    return "\n".join(base)


def _speak(
    system_path: Path,
    name: str,
    partner_last: Optional[str],
    *,
    model: str,
    temperature: float,
    max_tokens: int,
    topic: Optional[str],
) -> str:
    system = system_path.read_text(encoding="utf-8").strip()
    # Director beat will be set by caller; here we only craft user
    user = "(internal)"
    return ""  # placeholder, replaced by run loop


def run_duo(
    max_turns: int = 8,
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    topic: Optional[str] = None,
) -> None:
    load_dotenv(override=False)
    a_sys = Path("persona/char_a.system.txt")
    b_sys = Path("persona/char_b.system.txt")
    if not a_sys.exists() or not b_sys.exists():
        raise FileNotFoundError("persona system files not found under persona/")

    env_model = os.getenv("OPENAI_MODEL")
    resolved_model = _sanitize_model_name(env_model) if (model is None and env_model) else (model or "gpt-4o-mini")
    resolved_temperature = float(temperature if temperature is not None else os.getenv("OPENAI_TEMPERATURE", "0.7"))
    resolved_max_tokens = int(max_tokens if max_tokens is not None else os.getenv("OPENAI_MAX_TOKENS", "400"))
    resolved_topic = topic or os.getenv("TOPIC") or None

    policy = load_policy()

    last_a: Optional[str] = None
    last_b: Optional[str] = None

    for turn in range(1, max_turns + 1):
        beat = pick_beat(turn, policy)
        cut_cue = pick_cut(turn, max_turns, policy)
        _write_event({"event": "director", "turn": turn, "beat": beat, "cut_cue": cut_cue})

        if turn % 2 == 1:
            system = a_sys.read_text(encoding="utf-8").strip()
            user = _compose_user(last_b, resolved_topic, beat)
            who = "A"
        else:
            system = b_sys.read_text(encoding="utf-8").strip()
            user = _compose_user(last_a, resolved_topic, beat)
            who = "B"

        # One call with retry-once policy
        try:
            text = call(
                model=resolved_model,
                system=system,
                user=user,
                temperature=resolved_temperature,
                max_tokens=resolved_max_tokens,
            )
        except Exception as e:
            # retry once
            try:
                text = call(
                    model=resolved_model,
                    system=system,
                    user=user,
                    temperature=resolved_temperature,
                    max_tokens=resolved_max_tokens,
                )
            except Exception as e2:
                _write_event({"event": "error", "stage": "call", "turn": turn, "speaker": who, "message": str(e2)})
                raise

        # Enforce constraints hard regardless of model behavior
        text = hard_enforce(text)

        # Avoid summary/consensus words once
        summary_words = ["結論として", "合意", "まとめると", "総括すると", "最終的に"]
        if any(w in text for w in summary_words):
            avoid = "以下は使用禁止: 結論として/合意/まとめると/総括/最終的に。軽快に続けて。"
            user2 = f"{user}\n\n{avoid}"
            try:
                text2 = call(
                    model=resolved_model,
                    system=system,
                    user=user2,
                    temperature=resolved_temperature,
                    max_tokens=resolved_max_tokens,
                )
                text = hard_enforce(text2)
            except Exception:
                pass

        # Loop escape: if same leading 120 chars as previous same-speaker line
        prev_same = last_a if who == "A" else last_b
        def head120(s: Optional[str]) -> str:
            return (s or "")[:120]

        if prev_same and head120(prev_same) == head120(text):
            addon = "ところで、余談だけど一つだけ付け足すね。"
            text = hard_enforce(f"{text}\n{addon}")

        # If final turn and cut cue is TAG, add slight closing feeling without literal words
        if cut_cue == "TAG" and turn == max_turns:
            text = hard_enforce(f"{text}\nじゃ、ここでいったん切ろっか。")

        text = sanitize(text)

        _write_event({"event": "speak", "speaker": who, "turn": turn, "text": text})
        print(f"{who}: {text}")

        if who == "A":
            last_a = text
        else:
            last_b = text


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Duo Talk Entertainment: beats and cuts")
    p.add_argument("--max-turns", type=int, default=int(os.getenv("MAX_TURNS", "8")), help="Maximum total turns")
    p.add_argument("--model", type=str, default=None, help="Model name override (defaults to OPENAI_MODEL)")
    p.add_argument("--temperature", type=float, default=None, help="Sampling temperature (defaults to OPENAI_TEMPERATURE)")
    p.add_argument("--max-tokens", type=int, default=None, help="Max tokens (defaults to OPENAI_MAX_TOKENS)")
    p.add_argument("--topic", type=str, default=None, help="Conversation topic / theme (defaults to TOPIC)")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    load_dotenv(override=False)
    args = _parse_args(argv or [])
    _write_event({
        "event": "run_start",
        "mode": "entertain",
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
        print(f"Error: {e}")
        return 1
    finally:
        _write_event({"event": "run_end"})
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
