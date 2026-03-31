"""GitHub Copilot CLI provider."""
import os
import shutil
import subprocess
from typing import Generator

import requests

from .base import LLMProvider, register_provider


@register_provider("copilot")
class CopilotProvider(LLMProvider):
    """GitHub Copilot provider backed by the local `copilot` CLI."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = config.get("api_key", "")
        self.model = self._normalize_model(config.get("model", "claude-sonnet-4.5"))
        self.binary = self._find_vscode_shim() or shutil.which("copilot")
        self.node_runner = ["npx", "-y", "node@24"]

    def name(self) -> str:
        return f"GitHub Copilot ({self.model})"

    def _auth_error(self) -> RuntimeError:
        return RuntimeError(
            "GitHub Copilot CLI is not authenticated. Run `copilot login` in this Linux environment first."
        )

    def _missing_cli_error(self) -> RuntimeError:
        return RuntimeError(
            "GitHub Copilot CLI is not installed. Install it with `npm install -g @github/copilot` and run `copilot login` first."
        )

    def _find_vscode_shim(self) -> str | None:
        candidates = [
            os.path.expanduser("~/.local/bin/copilot"),
            os.path.expanduser("~/.config/Code/User/globalStorage/github.copilot-chat/copilotCli/copilot"),
            os.path.expanduser("~/.config/Code - Insiders/User/globalStorage/github.copilot-chat/copilotCli/copilot"),
        ]
        for path in candidates:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
        return None

    def _build_env(self) -> dict:
        env = os.environ.copy()
        env.setdefault("COPILOT_HOME", os.path.expanduser("~/.copilot"))
        node24_bin = os.path.expanduser("~/.local/node/current/bin")
        if os.path.isdir(node24_bin):
            env["PATH"] = f"{node24_bin}:{env.get('PATH', '')}" if env.get("PATH") else node24_bin
        if self.api_key:
            env["COPILOT_GITHUB_TOKEN"] = self.api_key
        return env

    def _build_command(self, prompt: str, stream: bool) -> list[str]:
        if not self.binary:
            raise self._missing_cli_error()
        return [
            *self.node_runner,
            self.binary,
            "--prompt", prompt,
            "--model", self.model,
            "--silent",
            "--no-color",
            "--stream", "on" if stream else "off",
            "--allow-all-tools",
            "--allow-all-paths",
            "--allow-all-urls",
            "--no-ask-user",
        ]

    def _normalize_model(self, model: str) -> str:
        if not model or "/" in model:
            return "claude-sonnet-4.5"
        return model

    def chat(self, messages: list[dict], stream: bool = True) -> str | Generator[str, None, None]:
        prompt = self._messages_to_prompt(messages)

        if stream:
            return self._stream_response(prompt)

        try:
            result = subprocess.run(
                self._build_command(prompt, stream=False),
                capture_output=True,
                text=True,
                env=self._build_env(),
                timeout=300,
                check=False,
            )
        except FileNotFoundError as e:
            raise self._missing_cli_error() from e
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("GitHub Copilot CLI timed out.") from e

        output = (result.stdout or "").strip()
        error_text = (result.stderr or "").strip()
        if result.returncode != 0:
            raise self._cli_error(error_text or output)
        if self._looks_missing(error_text) or self._looks_missing(output):
            raise self._missing_cli_error()

        return output

    def _stream_response(self, prompt: str) -> Generator[str, None, None]:
        try:
            proc = subprocess.Popen(
                self._build_command(prompt, stream=True),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=self._build_env(),
            )
        except FileNotFoundError as e:
            raise self._missing_cli_error() from e

        try:
            assert proc.stdout is not None
            for chunk in iter(lambda: proc.stdout.read(1), ""):
                if chunk:
                    yield chunk
            ret = proc.wait(timeout=300)
        except subprocess.TimeoutExpired as e:
            proc.kill()
            raise RuntimeError("GitHub Copilot CLI timed out.") from e

        stderr = proc.stderr.read() if proc.stderr else ""
        if ret != 0:
            raise self._cli_error(stderr)
        if self._looks_missing(stderr):
            raise self._missing_cli_error()

    def _messages_to_prompt(self, messages: list[dict]) -> str:
        lines = [
            "You are GitHub Copilot running inside the Agent-Nimi web chat.",
            "Respond naturally and helpfully to the latest user message.",
            "Use the prior conversation only as context.",
        ]
        history = []
        for msg in messages:
            content = (msg.get("content") or "").strip()
            role = msg.get("role", "user")
            if not content:
                continue
            if role == "system":
                continue
            if role == "assistant":
                history.append(f"Assistant: {content}")
            else:
                history.append(f"User: {content}")
        if history:
            lines.append("Conversation:")
            lines.extend(history)
        lines.append("Reply to the latest user message only.")
        return "\n\n".join(lines)

    def _cli_error(self, text: str) -> RuntimeError:
        message = (text or "").strip()
        lowered = message.lower()
        if "login" in lowered or "authenticate" in lowered or "not authenticated" in lowered:
            return self._auth_error()
        if self._looks_missing(lowered) or "not installed" in lowered:
            return self._missing_cli_error()
        if "402" in message or "no quota" in lowered or "quota exceeded" in lowered:
            return RuntimeError(f"[CopilotQuotaExhausted] {message}")
        return RuntimeError(message or "GitHub Copilot CLI failed.")

    def _looks_missing(self, text: str) -> bool:
        lowered = (text or "").lower()
        return "cannot find github copilot cli" in lowered

    def test_connection(self) -> bool:
        if not self.binary:
            return False
        try:
            result = subprocess.run(
                [*self.node_runner, self.binary, "version"],
                capture_output=True,
                text=True,
                env=self._build_env(),
                timeout=10,
                check=False,
            )
            return result.returncode == 0 and not self._looks_missing(result.stdout) and not self._looks_missing(result.stderr)
        except Exception:
            return False

    def deep_test_connection(self) -> tuple[bool, str]:
        """Verify GitHub Copilot CLI is installed and authenticated."""
        if not self.binary:
            return False, "copilot CLI not found — install with 'npm install -g @github/copilot' and run 'copilot login'"
        try:
            result = subprocess.run(
                [*self.node_runner, self.binary, "version"],
                capture_output=True,
                text=True,
                env=self._build_env(),
                timeout=10,
                check=False,
            )
            if result.returncode != 0:
                stderr = (result.stderr or result.stdout or "").strip()[:120]
                return False, f"copilot CLI failed: {stderr}"
            if self._looks_missing(result.stdout) or self._looks_missing(result.stderr):
                return False, "copilot CLI not found"
            return True, ""
        except FileNotFoundError:
            return False, "copilot CLI binary not found"
        except subprocess.TimeoutExpired:
            return False, "copilot CLI timed out"
        except Exception as e:
            return False, str(e)

    # ── Vision via GitHub Models REST API ────────────────────────────────

    def chat_vision(
        self,
        messages: list[dict],
        images: list[str],
        stream: bool = False,
    ) -> str:
        """Send messages + images via the GitHub Models REST API.

        The CLI doesn't support image input, so we fall back to the REST
        endpoint (``self.base_url``) which accepts OpenAI-compatible
        multi-modal content arrays.
        """
        if not self.api_key:
            # No API key — fall back to base class (text-only)
            return super().chat_vision(messages, images, stream)

        base = (self.config.get("base_url") or "https://models.github.ai").rstrip("/")
        url = f"{base}/chat/completions"
        # Use a vision-capable model; gpt-4o handles images well on GitHub Models
        vision_model = self.config.get("vision_model") or "gpt-4o"

        # Build vision messages: inject images into the last user message
        vision_msgs: list[dict] = []
        for msg in messages:
            vision_msgs.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

        # Find the last user message and replace its content with a content array
        for i in range(len(vision_msgs) - 1, -1, -1):
            if vision_msgs[i].get("role") == "user":
                text = vision_msgs[i].get("content", "")
                blocks: list[dict] = [{"type": "text", "text": text}]
                for img in images:
                    if isinstance(img, str) and img.startswith("data:"):
                        _, b64 = img.split(",", 1)
                    else:
                        b64 = img
                    blocks.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "auto"},
                    })
                vision_msgs[i] = {"role": "user", "content": blocks}
                break

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": vision_model,
            "messages": vision_msgs,
            "stream": False,
            "max_tokens": 2048,
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=120)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            # Fall back to text-only via base class
            return super().chat_vision(messages, images, stream)
