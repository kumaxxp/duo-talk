"""
LLM API client for OpenAI-compatible endpoints (Ollama, LM Studio, etc.)
"""

import time
from typing import Optional, List, Tuple
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

    def call_with_history(
        self,
        system: str,
        history: List[Tuple[str, str]],  # [(speaker, text), ...]
        current_speaker: str,  # "A" or "B"
        current_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 200,
        retries: int = 2,
        frequency_penalty: float = 0.5,
        presence_penalty: float = 0.3,
    ) -> str:
        """
        Call the LLM with conversation history as separate messages.

        Args:
            system: System prompt
            history: List of (speaker, text) tuples for conversation history
            current_speaker: Current speaker's ID ("A" or "B")
            current_prompt: Current turn's prompt (scene context, instructions, etc.)
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response
            retries: Number of retries on failure
            frequency_penalty: Penalty for repeated tokens
            presence_penalty: Penalty for tokens already in text

        Returns:
            Response text from the LLM
        """
        # Build messages array with proper role separation
        messages = [{"role": "system", "content": system}]

        # Add conversation history with alternating roles
        # user = 相手の発言, assistant = 自分の過去の発言
        for speaker, text in history:
            if speaker == current_speaker:
                # 自分の過去の発言 → assistant
                messages.append({"role": "assistant", "content": text})
            else:
                # 相手の発言 → user
                messages.append({"role": "user", "content": text})

        # Add current prompt as user message
        messages.append({"role": "user", "content": current_prompt})

        for attempt in range(retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    frequency_penalty=frequency_penalty,
                    presence_penalty=presence_penalty,
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                if attempt == retries - 1:
                    raise
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
