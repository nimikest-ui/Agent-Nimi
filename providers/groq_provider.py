"""
Groq LLM Provider (OpenAI-compatible API)
"""
import json
import requests
from typing import Generator
from .base import LLMProvider, register_provider


@register_provider("groq")
class GroqProvider(LLMProvider):
    """Groq API provider — fast inference via OpenAI-compatible endpoint."""

    BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = config.get("api_key", "")
        self.model = config.get("model", "llama-3.3-70b-versatile")

    def name(self) -> str:
        return f"Groq ({self.model})"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def chat(self, messages: list[dict], stream: bool = True) -> str | Generator[str, None, None]:
        url = f"{self.BASE_URL}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }

        if stream:
            return self._stream_response(url, payload)
        else:
            payload["stream"] = False
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=120)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    def _stream_response(self, url: str, payload: dict) -> Generator[str, None, None]:
        with requests.post(url, json=payload, headers=self._headers(), stream=True, timeout=120) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line:
                    line_str = line.decode("utf-8")
                    if line_str.startswith("data: "):
                        data_str = line_str[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue

    def test_connection(self) -> bool:
        try:
            resp = requests.get(
                f"{self.BASE_URL}/models",
                headers=self._headers(),
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False
