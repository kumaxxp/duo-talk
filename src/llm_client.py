"""
LLM API client for OpenAI-compatible endpoints (Ollama, LM Studio, etc.)
"""

import time
from typing import Optional
from openai import OpenAI

from src.config import config


class LLMClient:
    """Wrapper around OpenAI-compatible LLM API"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        self.base_url = base_url or config.openai_base_url
        self.api_key = api_key or config.openai_api_key
        self.model = model or config.openai_model
        self.timeout = timeout or config.timeout

        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
        )

    def call(
        self,
        system: str,
        user: str,
        temperature: float = 0.7,
        max_tokens: int = 400,
        retries: int = 2,
        frequency_penalty: float = 0.5,
        presence_penalty: float = 0.3,
    ) -> str:
        """
        Call the LLM and return the response text.

        Args:
            system: System prompt
            user: User message
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response
            retries: Number of retries on failure
            frequency_penalty: Penalty for repeated tokens (0.0-2.0, higher = less repetition)
            presence_penalty: Penalty for tokens already in text (0.0-2.0)

        Returns:
            Response text from the LLM
        """
        for attempt in range(retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    frequency_penalty=frequency_penalty,
                    presence_penalty=presence_penalty,
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                if attempt == retries - 1:
                    raise
                # Exponential backoff
                wait_time = 2 ** attempt
                print(f"LLM call failed (attempt {attempt + 1}/{retries}), retrying in {wait_time}s...")
                time.sleep(wait_time)

        raise RuntimeError("LLM call failed after all retries")


# Global client instance
_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Get or create global LLM client"""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


def set_llm_client(client: LLMClient) -> None:
    """Set global LLM client"""
    global _client
    _client = client
