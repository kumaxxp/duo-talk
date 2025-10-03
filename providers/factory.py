import os
from typing import Optional

from .speaker_provider import SpeakerProvider


def create_speaker_a() -> Optional[SpeakerProvider]:
    """Create A-side provider based on env configuration.

    Returns None if mode is not set to an external provider (i.e., keep local flow).
    """
    mode = (os.getenv("SPEAKER_A_MODE") or "").strip().lower()
    if mode in {"", "local"}:
        return None
    if mode == "http":
        from .speaker_http import SpeakerAHttpProvider

        base = os.getenv("SPEAKER_A_HTTP_BASE")
        token = os.getenv("SPEAKER_A_AUTH_TOKEN")
        return SpeakerAHttpProvider(base_url=base, auth_token=token)
    # Future: MCP provider
    if mode == "mcp":
        from .speaker_mcp import SpeakerAMcpProvider
        return SpeakerAMcpProvider()
    raise ValueError(f"Unknown SPEAKER_A_MODE: {mode}")


__all__ = ["create_speaker_a"]
