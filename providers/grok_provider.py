"""
Grok (xAI) LLM Provider
Supports both Chat Completions API (/v1/chat/completions) and
Responses API (/v1/responses) for multi-agent models.
"""
import json
import requests
from typing import Generator
from .base import LLMProvider, register_provider


@register_provider("grok")
class GrokProvider(LLMProvider):
    """xAI Grok API provider (OpenAI-compatible)."""

    # Session-level usage counters (survives across chat calls)
    _session_usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "cached_tokens": 0,
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "request_count": 0,
    }

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = config.get("base_url", "https://api.x.ai/v1")
        self.api_key = config.get("api_key", "")
        self.model = config.get("model", "grok-3")
        self._last_rate_limit = {}   # captured from response headers

    def name(self) -> str:
        return f"Grok ({self.model})"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _is_multi_agent(self) -> bool:
        """Check if the current model requires the Responses API (multi-agent)."""
        return "multi-agent" in self.model

    # ── Chat Completions path (standard models) ──────────────────

    def chat(self, messages: list[dict], stream: bool = True) -> str | Generator[str, None, None]:
        if self._is_multi_agent():
            return self._responses_chat(messages, stream)

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
            if resp.status_code == 400:
                detail = resp.text[:300]
                raise RuntimeError(f"Grok API rejected the request (400): {detail}")
            resp.raise_for_status()
            self._capture_rate_limits(resp)
            body = resp.json()
            self._accumulate_usage(body.get("usage"))
            return body["choices"][0]["message"]["content"]

    def _capture_rate_limits(self, resp):
        """Capture rate-limit headers from an API response."""
        h = resp.headers
        rl = {}
        for key in ("x-ratelimit-limit-requests", "x-ratelimit-remaining-requests",
                    "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens",
                    "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
            val = h.get(key)
            if val is not None:
                rl[key.replace("x-ratelimit-", "")] = val
        if rl:
            self._last_rate_limit = rl

    def _accumulate_usage(self, usage: dict):
        """Add a response's usage object to session counters."""
        if not usage:
            return
        s = GrokProvider._session_usage
        s["prompt_tokens"] += usage.get("prompt_tokens", 0)
        s["completion_tokens"] += usage.get("completion_tokens", 0)
        s["total_tokens"] += usage.get("total_tokens", 0)
        s["request_count"] += 1
        # Reasoning tokens from details
        details = usage.get("completion_tokens_details", {})
        s["reasoning_tokens"] += details.get("reasoning_tokens", 0)
        # Cached tokens
        prompt_details = usage.get("prompt_tokens_details", {})
        s["cached_tokens"] += prompt_details.get("cached_tokens", 0)
        # Cost in USD (ticks = 1/10,000,000,000 USD)
        cost_ticks = usage.get("cost_in_usd_ticks", 0)
        if cost_ticks:
            s["total_cost_usd"] += cost_ticks / 10_000_000_000

    def get_session_usage(self) -> dict:
        """Return accumulated session token usage."""
        return dict(GrokProvider._session_usage)

    def get_rate_limits(self) -> dict:
        """Return last captured rate limit headers."""
        return dict(self._last_rate_limit)

    @classmethod
    def reset_session_usage(cls):
        """Reset session counters."""
        cls._session_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "cached_tokens": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "request_count": 0,
        }

    def _stream_response(self, url: str, payload: dict) -> Generator[str, None, None]:
        with requests.post(url, json=payload, headers=self._headers(), stream=True, timeout=300) as resp:
            if resp.status_code == 400:
                detail = resp.text[:300]
                raise RuntimeError(f"Grok API rejected the request (400): {detail}")
            resp.raise_for_status()
            self._capture_rate_limits(resp)
            for line in resp.iter_lines():
                if line:
                    line_str = line.decode("utf-8")
                    if line_str.startswith("data: "):
                        data_str = line_str[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            # Capture usage from the final chunk
                            if "usage" in data:
                                self._accumulate_usage(data["usage"])
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            if "content" in delta and delta["content"]:
                                yield delta["content"]
                        except json.JSONDecodeError:
                            continue

    # ── Responses API path (multi-agent models) ──────────────────

    def _responses_chat(self, messages: list[dict], stream: bool = True) -> str | Generator[str, None, None]:
        """Use /v1/responses endpoint for multi-agent models."""
        url = f"{self.base_url}/responses"

        # Convert messages to Responses API 'input' format
        input_msgs = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            # Responses API uses 'developer' instead of 'system'
            if role == "system":
                role = "developer"
            input_msgs.append({"role": role, "content": content})

        payload = {
            "model": self.model,
            "input": input_msgs,
            "stream": stream,
        }

        if stream:
            return self._stream_responses(url, payload)
        else:
            payload["stream"] = False
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=600)
            if resp.status_code == 400:
                detail = resp.text[:300]
                raise RuntimeError(f"Grok Responses API rejected the request (400): {detail}")
            resp.raise_for_status()
            self._capture_rate_limits(resp)
            body = resp.json()
            self._accumulate_usage(body.get("usage"))
            return self._extract_responses_text(body)

    def _extract_responses_text(self, data: dict) -> str:
        """Extract text content from a Responses API JSON response."""
        for item in data.get("output", []):
            if item.get("type") == "message":
                for block in item.get("content", []):
                    if block.get("type") == "output_text":
                        return block.get("text", "")
        # Fallback: try first output item content
        output = data.get("output", [])
        if output and isinstance(output, list):
            first = output[0]
            if isinstance(first, dict):
                content = first.get("content", [])
                if content and isinstance(content, list):
                    return content[0].get("text", str(content))
        return str(data)

    def _stream_responses(self, url: str, payload: dict) -> Generator[str, None, None]:
        """Stream from /v1/responses using SSE.
        
        Responses API streams events like:
          data: {"type": "response.output_text.delta", "delta": "token"}
          data: {"type": "response.completed", ...}
        """
        with requests.post(url, json=payload, headers=self._headers(), stream=True, timeout=600) as resp:
            if resp.status_code == 400:
                detail = resp.text[:300]
                raise RuntimeError(f"Grok Responses API rejected the request (400): {detail}")
            resp.raise_for_status()
            self._capture_rate_limits(resp)
            for line in resp.iter_lines():
                if not line:
                    continue
                line_str = line.decode("utf-8")
                if not line_str.startswith("data: "):
                    continue
                data_str = line_str[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                etype = event.get("type", "")
                # Text delta tokens
                if etype == "response.output_text.delta":
                    delta = event.get("delta", "")
                    if delta:
                        yield delta
                # Also handle content_part delta (alternate format)
                elif etype == "response.content_part.delta":
                    delta = event.get("delta", {})
                    if isinstance(delta, dict):
                        text = delta.get("text", "")
                        if text:
                            yield text
                    elif isinstance(delta, str) and delta:
                        yield delta
                # Capture usage from completed event
                elif etype in ("response.completed", "response.done"):
                    resp_data = event.get("response", event)
                    if "usage" in resp_data:
                        self._accumulate_usage(resp_data["usage"])
                    break

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
