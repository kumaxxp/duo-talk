"""Provider package for pluggable speaker backends.

This package introduces a SpeakerProvider protocol and concrete providers
such as the HTTP-based provider for Sumigaseyana (A side character).

Default duo flows remain unchanged unless explicitly wired to use a provider.
"""

from .speaker_provider import SpeakerProvider  # re-export

__all__ = [
    "SpeakerProvider",
]

