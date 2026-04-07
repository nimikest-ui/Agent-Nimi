"""
Grok (xAI) LLM Provider
"""
import json
import requests
from typing import Generator
from .base import LLMProvider, register_provider


@register_provider("grok")
class GrokProvider(LLMProvider):
    """xAI Grok API provider (OpenAI-compatible)."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = config.get("base_url", "https://api.x.ai/v1")
        self.api_key = config.get("api_key", "")
        self.model = config.get("model", "grok-3")

    def name(self) -> str:
        return f"Grok ({self.model})"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def chat(self, messages: list[dict], stream: bool = True) -> str | Generator[str, None, None]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "max_tokens": 4096,
        }

        if stream:
            return self._stream_response(url, payload)
        else:
            payload["stream"] = False
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=300)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    def _stream_response(self, url: str, payload: dict) -> Generator[str, None, None]:
        with requests.post(url, json=payload, headers=self._headers(), stream=True, timeout=300) as resp:
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
                            if "content" in delta and delta["content"]:
                                yield delta["content"]
                        except json.JSONDecodeError:
                            continue

    def chat_vision(
        self,
        messages: list[dict],
        images: list[str],
        stream: bool = False,
    ) -> str:
        """Send text + images to grok-2-vision-1212 or the configured model if it supports vision."""
        import base64 as _b64

        # Build content list with interleaved text and image blocks
        vision_messages: list[dict] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content") or ""
            if role == "user" and not vision_messages or messages.index(msg) == len(messages) - 1:
                # Attach images to the LAST user message only
                vision_messages.append({"role": role, "content": content})
            else:
                vision_messages.append({"role": role, "content": content})

        # Inject images into the last user message as a content array
        for i in range(len(vision_messages) - 1, -1, -1):
            if vision_messages[i].get("role") == "user":
                text_content = vision_messages[i].get("content", "")
                content_blocks: list[dict] = [{"type": "text", "text": text_content}]
                for img in images:
                    # Normalise: strip data URI prefix to get raw base64
                    if isinstance(img, str) and img.startswith("data:"):
                        # e.g. data:image/png;base64,XXXX
                        _, b64_part = img.split(",", 1)
                    else:
                        b64_part = img
                    content_blocks.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{b64_part}",
                            "detail": "high",
                        },
                    })
                vision_messages[i] = {"role": "user", "content": content_blocks}
                break

        # Use a vision-capable model; prefer the dedicated vision model if configured
        vision_model = self.config.get("vision_model") or "grok-2-vision-1212"
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": vision_model,
            "messages": vision_messages,
            "stream": False,
            "max_tokens": 2048,
        }
        resp = requests.post(url, json=payload, headers=self._headers(), timeout=120)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def test_connection(self) -> bool:
        if not self.api_key:
            return False
        try:
            resp = requests.get(
                f"{self.base_url}/models",
                headers=self._headers(),
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def deep_test_connection(self) -> tuple[bool, str]:
        """Verify Grok works with a real tiny chat request."""
        if not self.api_key:
            return False, "no API key configured"
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                json={"model": self.model, "messages": [{"role": "user", "content": "hi"}], "stream": False, "max_tokens": 5},
                headers=self._headers(),
                timeout=20,
            )
            if resp.status_code == 200:
                return True, ""
            body = resp.text.strip()[:120]
            if resp.status_code == 401:
                return False, f"API key invalid or expired"
            if resp.status_code == 429:
                return False, f"rate limited / quota exhausted"
            return False, f"HTTP {resp.status_code}: {body}"
        except requests.ConnectionError:
            return False, "cannot reach api.x.ai"
        except requests.Timeout:
            return False, "request timed out"
        except Exception as e:
            return False, str(e)
