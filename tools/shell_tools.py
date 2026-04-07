"""
Shell Tools - Execute commands, background processes
"""
import subprocess
import shlex
import re
import os
import signal
import threading
import time
from .registry import tool

# Track background processes
_bg_processes: dict[int, subprocess.Popen] = {}
_bg_counter = 0

# ── Network disconnect failsafe ───────────────────────────────────────────────

# Commands that can sever the agent's network access.
# Checked case-insensitively as substrings of the command string.
NETWORK_DISCONNECT_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bip\s+link\s+set\s+\w+\s+down\b"),
    re.compile(r"\bifdown\b"),
    re.compile(r"\bifconfig\s+\w+\s+down\b"),
    re.compile(r"\bnmcli\s+(dev|device|con|connection)\s+(down|disconnect)\b"),
    re.compile(r"\bnetwork(?:ctl)?\s+(?:disconnect|disable)\b"),
    re.compile(r"\bip\s+route\s+(?:del|flush)\s+default\b"),
    re.compile(r"\biptables\b.*(-P\s+(?:INPUT|OUTPUT|FORWARD)\s+DROP|-F\s+(?:INPUT|OUTPUT)|-j\s+DROP)"),
    re.compile(r"\bufw\s+(?:disable|deny\s+out)\b"),
    re.compile(r"\brfkill\s+(?:block|disable)\b"),
    re.compile(r"\bsystemctl\s+(?:stop|disable)\s+NetworkManager\b"),
    re.compile(r"\bsystemctl\s+(?:stop|disable)\s+networking\b"),
    re.compile(r"\bsystemctl\s+(?:stop|disable)\s+network(?:d)?\b"),
]


def is_network_disconnect_command(command: str) -> bool:
    """Return True if the command matches a known network-disruption pattern."""
    for pat in NETWORK_DISCONNECT_PATTERNS:
        if pat.search(command):
            return True
    return False


# ── Connectivity check & auto-restore ────────────────────────────────────────

def _ping_check(hosts: list[str]) -> bool:
    """Return True if at least one host is reachable via ICMP."""
    for host in hosts:
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "3", host],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass
    return False


def _restore_network() -> str:
    """Attempt to restore internet connectivity using NetworkManager + dhclient."""
    steps: list[str] = []

    # 1. Start / restart NetworkManager
    r = subprocess.run(
        ["systemctl", "start", "NetworkManager"],
        capture_output=True, text=True, timeout=15,
    )
    steps.append(f"systemctl start NetworkManager → exit {r.returncode}")

    time.sleep(3)  # give NM a moment to come up

    # 2. Tell NM to reconnect all interfaces
    r2 = subprocess.run(
        ["nmcli", "networking", "on"],
        capture_output=True, text=True, timeout=10,
    )
    steps.append(f"nmcli networking on → exit {r2.returncode}")

    time.sleep(5)

    # 3. If still no connectivity, fallback: bring up default interface + dhclient
    if not _ping_check(["1.1.1.1", "8.8.8.8"]):
        # Detect default interface from routing table
        iface_result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True, timeout=5,
        )
        m = re.search(r"dev\s+(\S+)", iface_result.stdout)
        iface = m.group(1) if m else "eth0"

        r3 = subprocess.run(
            ["ip", "link", "set", iface, "up"],
            capture_output=True, text=True, timeout=10,
        )
        steps.append(f"ip link set {iface} up → exit {r3.returncode}")

        r4 = subprocess.run(
            ["dhclient", "-v", iface],
            capture_output=True, text=True, timeout=30,
        )
        steps.append(f"dhclient {iface} → exit {r4.returncode}")

    ok = _ping_check(["1.1.1.1", "8.8.8.8"])
    steps.append(f"connectivity check → {'OK' if ok else 'STILL DOWN'}")
    return "\n".join(steps)


# ── Watchdog thread ───────────────────────────────────────────────────────────

class _NetworkWatchdog:
    """Background thread that monitors internet reachability.

    If connectivity drops, automatically re-invokes NetworkManager
    and logs the event. Controlled via start() / stop().
    """

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_evt = threading.Event()
        self.enabled = False
        self.interval = 30
        self.hosts: list[str] = ["1.1.1.1", "8.8.8.8"]
        self._restore_log: list[dict] = []    # [{time, steps, recovered}]
        self._lock = threading.Lock()

    def configure(self, enabled: bool, interval: int, hosts: list[str]) -> None:
        self.enabled = enabled
        self.interval = max(10, interval)
        self.hosts = hosts or ["1.1.1.1", "8.8.8.8"]

    def start(self) -> None:
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="net-watchdog")
        self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()

    def get_log(self) -> list[dict]:
        with self._lock:
            return list(self._restore_log)

    def _run(self) -> None:
        """Main watchdog loop."""
        was_down = False
        while not self._stop_evt.wait(timeout=self.interval):
            reachable = _ping_check(self.hosts)
            if not reachable:
                if not was_down:
                    # First failure — attempt restore
                    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
                    steps = _restore_network()
                    recovered = _ping_check(self.hosts)
                    entry = {"time": ts, "steps": steps, "recovered": recovered}
                    with self._lock:
                        self._restore_log.append(entry)
                        if len(self._restore_log) > 50:
                            self._restore_log = self._restore_log[-50:]
                    was_down = not recovered
                # else: still down after restore — wait for next cycle
            else:
                was_down = False


_watchdog = _NetworkWatchdog()


def start_network_watchdog(config: dict | None = None) -> None:
    """Start the watchdog using config from the safety section."""
    safety = (config or {}).get("safety", {})
    _watchdog.configure(
        enabled=safety.get("network_watchdog", True),
        interval=int(safety.get("network_watchdog_interval", 30)),
        hosts=safety.get("network_watchdog_hosts", ["1.1.1.1", "8.8.8.8"]),
    )
    _watchdog.start()


# ── Agent-facing tool ─────────────────────────────────────────────────────────

@tool(
    name="network_reconnect",
    description=(
        "Emergency network restore tool. Starts NetworkManager, enables networking, "
        "and brings up the default interface via dhclient if needed. "
        "Use this if the agent or a pentest command has accidentally dropped internet connectivity."
    ),
    manifest={
        "action_class": "irreversible",
        "capabilities": ["sysadmin", "network"],
        "trust_tier": "tier_2",
        "provider_affinity": "any",
    },
)
def network_reconnect() -> str:
    """Restore network connectivity via NetworkManager."""
    before = _ping_check(["1.1.1.1", "8.8.8.8"])
    if before:
        return "[network_reconnect] Connectivity already OK — nothing to do."

    steps = _restore_network()
    after = _ping_check(["1.1.1.1", "8.8.8.8"])
    status = "RESTORED" if after else "STILL DOWN — manual intervention required"
    return f"[network_reconnect] {status}\n\n{steps}"


@tool(
    name="network_status",
    description=(
        "Check current internet connectivity status and view the watchdog restore log. "
        "Returns reachability, default route, and a history of any auto-restore attempts."
    ),
    manifest={
        "action_class": "read_only",
        "capabilities": ["network", "sysadmin"],
        "trust_tier": "tier_1",
        "provider_affinity": "any",
    },
)
def network_status() -> str:
    """Report current connectivity and watchdog history."""
    reachable = _ping_check(["1.1.1.1", "8.8.8.8"])

    # Default route
    try:
        route_res = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True, timeout=5,
        )
        route = route_res.stdout.strip() or "(no default route)"
    except Exception:
        route = "(could not read routing table)"

    lines = [
        f"Internet: {'REACHABLE' if reachable else 'UNREACHABLE'}",
        f"Default route: {route}",
        f"Watchdog: {'running' if _watchdog._thread and _watchdog._thread.is_alive() else 'stopped'}"
        f"  (interval={_watchdog.interval}s, hosts={_watchdog.hosts})",
    ]

    log = _watchdog.get_log()
    if log:
        lines.append(f"\nAuto-restore history ({len(log)} event(s)):")
        for entry in log[-5:]:
            lines.append(
                f"  [{entry['time']}] recovered={'YES' if entry['recovered'] else 'NO'}\n"
                f"    {entry['steps'].replace(chr(10), chr(10) + '    ')}"
            )
    else:
        lines.append("\nNo auto-restore events recorded.")

    return "\n".join(lines)



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
