from typing import Protocol, Tuple, Dict, Any


class SpeakerProvider(Protocol):
    """Minimal provider interface for generating A-side utterances.

    Implementations should be side-effect free and raise exceptions on hard
    failures. On success, return a tuple of (reply_text, meta_dict).
    The meta dict should be JSON-serializable.
    """

    def generate(
        self,
        user_text: str,
        *,
        run_id: str,
        top_k: int,
        filters: Dict[str, Any],
        timeout_ms: int,
    ) -> Tuple[str, Dict[str, Any]]:
        ...

