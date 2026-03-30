"""
Shell Tools - Execute commands, background processes
"""
import subprocess
import shlex
import re
import os
import signal
import threading
from .registry import tool

# Track background processes
_bg_processes: dict[int, subprocess.Popen] = {}
_bg_counter = 0


def _run_command(command: str, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "TERM": "dumb", "DEBIAN_FRONTEND": "noninteractive"},
    )


def _format_result(result: subprocess.CompletedProcess) -> str:
    output = ""
    if result.stdout:
        output += result.stdout
    if result.stderr:
        output += ("\n[STDERR]\n" + result.stderr) if output else result.stderr
    if result.returncode != 0:
        output += f"\n[Exit code: {result.returncode}]"
    return output.strip() if output.strip() else "[Command completed with no output]"


def _strip_sudo_prefix(command: str) -> str:
    """Remove leading sudo and its options to get the underlying command."""
    text = (command or "").strip()
    if not text.startswith("sudo"):
        return text

    parts = shlex.split(text)
    if not parts or parts[0] != "sudo":
        return text

    idx = 1
    while idx < len(parts):
        token = parts[idx]
        if token == "--":
            idx += 1
            break
        if token.startswith("-"):
            idx += 1
            continue
        break

    underlying = parts[idx:]
    return " ".join(shlex.quote(p) for p in underlying) if underlying else ""


@tool("shell_exec", "Execute a shell command and return output", manifest={"action_class": "irreversible", "capabilities": ["code", "sysadmin"], "trust_tier": "tier_2"})
def shell_exec(command: str, timeout: int = 120) -> str:
    """Execute a shell command with timeout."""
    try:
        result = _run_command(command, timeout)
        stderr_lower = (result.stderr or "").lower()
        command_stripped = command.strip()

        # Privilege fallback: if sudo is blocked by container policy, retry without sudo.
        if (
            command_stripped.startswith("sudo ")
            and "no new privileges" in stderr_lower
        ):
            retry_command = _strip_sudo_prefix(command_stripped)
            if not retry_command:
                return (
                    "[sudo blocked by no_new_privileges policy]\n"
                    "[Privilege hint] Run this in a root-capable shell (or disable no_new_privileges in the container runtime) and retry."
                )
            retry = _run_command(retry_command, timeout)
            retry_output = _format_result(retry)
            note = "[sudo blocked by no_new_privileges policy; retried without sudo]"
            if retry.returncode == 0:
                return note + "\n" + retry_output
            return (
                note
                + "\n"
                + retry_output
                + "\n[Privilege hint] Run this in a root-capable shell (or disable no_new_privileges in the container runtime) and retry."
            )

        return _format_result(result)
    except subprocess.TimeoutExpired:
        return f"[Command timed out after {timeout}s]"
    except Exception as e:
        return f"[Error: {e}]"


@tool("shell_exec_background", "Run a command in the background, returns a process ID", manifest={"action_class": "irreversible", "capabilities": ["code", "sysadmin"], "trust_tier": "tier_2"})
def shell_exec_background(command: str) -> str:
    """Start a background process."""
    global _bg_counter
    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=os.setsid,
        )
        _bg_counter += 1
        _bg_processes[_bg_counter] = proc
        return f"Background process started (ID: {_bg_counter}, PID: {proc.pid})"
    except Exception as e:
        return f"[Error starting background process: {e}]"


@tool("bg_process_status", "Check status of a background process", manifest={"action_class": "read_only"})
def bg_process_status(process_id: int) -> str:
    """Check status of a background process."""
    proc = _bg_processes.get(int(process_id))
    if not proc:
        return f"No background process with ID {process_id}"
    poll = proc.poll()
    if poll is None:
        return f"Process {process_id} (PID {proc.pid}): RUNNING"
    else:
        stdout = proc.stdout.read() if proc.stdout else ""
        stderr = proc.stderr.read() if proc.stderr else ""
        output = f"Process {process_id} (PID {proc.pid}): FINISHED (exit code {poll})"
        if stdout:
            output += f"\n[STDOUT]\n{stdout}"
        if stderr:
            output += f"\n[STDERR]\n{stderr}"
        return output


@tool("bg_process_kill", "Kill a background process", manifest={"action_class": "irreversible", "capabilities": ["sysadmin"]})
def bg_process_kill(process_id: int) -> str:
    """Kill a background process."""
    proc = _bg_processes.get(int(process_id))
    if not proc:
        return f"No background process with ID {process_id}"
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=5)
        return f"Process {process_id} (PID {proc.pid}) terminated"
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        return f"Process {process_id} (PID {proc.pid}) force killed"
    except Exception as e:
        return f"Error killing process: {e}"
