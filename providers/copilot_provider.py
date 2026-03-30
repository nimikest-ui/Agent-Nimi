"""GitHub Copilot CLI provider."""
import os
import shutil
import subprocess
from typing import Generator

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
