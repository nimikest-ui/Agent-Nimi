"""World-State Tracker (Phase 8)
──────────────────────────────
Maintains a structured model of observed environment facts so the agent
loop can inject a concise summary instead of relying solely on long
message history for grounding.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class FileObservation:
    path: str
    size: int = 0
    content_hash: str = ""
    snippet: str = ""


@dataclass
class HostObservation:
    host: str
    ports: dict[int, str] = field(default_factory=dict)  # port → service
    os_guess: str = ""


class WorldState:
    """Track observed facts about the execution environment.

    Updated automatically after each tool call (``update_from_tool_result``).
    Provides a concise ``summary()`` for injection into the LLM context.
    """

    def __init__(self) -> None:
        self.files: dict[str, FileObservation] = {}
        self.hosts: dict[str, HostObservation] = {}
        self.services: dict[str, str] = {}          # service_name → status
        self.packages: set[str] = set()
        self.env_facts: dict[str, str] = {}          # key → value misc facts
        self._change_count: int = 0

    # ── Public API ────────────────────────────────────────────────────────

    def update_from_tool_result(
        self,
        tool_name: str,
        args: dict[str, Any],
        output: str,
        success: bool,
    ) -> None:
        """Parse a tool's output and update the world model."""
        if not success:
            return

        handler = self._HANDLERS.get(tool_name)
        if handler:
            handler(self, args, output)

    def summary(self, max_chars: int = 1200) -> str:
        """Concise plaintext summary for LLM context injection."""
        parts: list[str] = []

        if self.files:
            top_files = list(self.files.values())[-8:]
            parts.append("Files observed: " + ", ".join(
                f"{f.path} ({f.size}B)" for f in top_files
            ))

        if self.hosts:
            for h in list(self.hosts.values())[-4:]:
                ports_str = ", ".join(
                    f"{p}/{s}" for p, s in sorted(h.ports.items())
                ) or "no open ports"
                parts.append(f"Host {h.host}: {ports_str}")

        if self.services:
            parts.append("Services: " + ", ".join(
                f"{k}={v}" for k, v in list(self.services.items())[-6:]
            ))

        if self.packages:
            parts.append(f"Packages installed: {', '.join(sorted(self.packages)[:10])}")

        if self.env_facts:
            parts.append("Env: " + "; ".join(
                f"{k}={v}" for k, v in list(self.env_facts.items())[-6:]
            ))

        text = "\n".join(parts)
        return text[:max_chars] if text else ""

    def diff(self, other: "WorldState") -> dict[str, Any]:
        """Return what changed between *self* (newer) and *other* (older)."""
        changes: dict[str, Any] = {}
        new_files = set(self.files) - set(other.files)
        if new_files:
            changes["new_files"] = list(new_files)
        new_hosts = set(self.hosts) - set(other.hosts)
        if new_hosts:
            changes["new_hosts"] = list(new_hosts)
        new_pkgs = self.packages - other.packages
        if new_pkgs:
            changes["new_packages"] = list(new_pkgs)
        return changes

    @property
    def change_count(self) -> int:
        return self._change_count

    def to_dict(self) -> dict:
        return {
            "files": {k: asdict(v) for k, v in self.files.items()},
            "hosts": {k: asdict(v) for k, v in self.hosts.items()},
            "services": dict(self.services),
            "packages": sorted(self.packages),
            "env_facts": dict(self.env_facts),
        }

    # ── Internal handlers per tool ────────────────────────────────────────

    def _handle_file_read(self, args: dict, output: str) -> None:
        path = args.get("path", "")
        if not path or output.startswith("["):
            return
        self.files[path] = FileObservation(
            path=path,
            size=len(output),
            content_hash=hashlib.md5(output[:2000].encode()).hexdigest(),
            snippet=output[:120].replace("\n", " "),
        )
        self._change_count += 1

    def _handle_file_write(self, args: dict, output: str) -> None:
        path = args.get("path", "")
        content = args.get("content", "")
        if path:
            self.files[path] = FileObservation(
                path=path,
                size=len(content),
                content_hash=hashlib.md5(content[:2000].encode()).hexdigest(),
                snippet=content[:120].replace("\n", " "),
            )
            self._change_count += 1

    def _handle_nmap(self, args: dict, output: str) -> None:
        target = args.get("target", "unknown")
        obs = self.hosts.get(target, HostObservation(host=target))
        # Parse "PORT   STATE SERVICE" lines
        for m in re.finditer(r"(\d+)/(?:tcp|udp)\s+open\s+(\S+)", output):
            port, service = int(m.group(1)), m.group(2)
            obs.ports[port] = service
        self.hosts[target] = obs
        self._change_count += 1

    def _handle_system_status(self, _args: dict, output: str) -> None:
        # Extract hostname
        for line in output.split("\n")[:3]:
            line = line.strip()
            if line and not line.startswith("==="):
                self.env_facts["hostname"] = line.split()[0]
                break
        # Extract memory line
        m = re.search(r"Mem:\s+(\S+)\s+(\S+)\s+(\S+)", output)
        if m:
            self.env_facts["mem_total"] = m.group(1)
            self.env_facts["mem_used"] = m.group(2)
        self._change_count += 1

    def _handle_service_status(self, args: dict, output: str) -> None:
        svc = args.get("service", "")
        if "active (running)" in output.lower():
            self.services[svc] = "running"
        elif "inactive" in output.lower():
            self.services[svc] = "inactive"
        elif "failed" in output.lower():
            self.services[svc] = "failed"
        else:
            self.services[svc] = "unknown"
        self._change_count += 1

    def _handle_pkg_install(self, args: dict, output: str) -> None:
        pkgs = args.get("packages", "")
        for pkg in pkgs.split():
            self.packages.add(pkg)
        self._change_count += 1

    def _handle_pkg_remove(self, args: dict, output: str) -> None:
        pkgs = args.get("packages", "")
        for pkg in pkgs.split():
            self.packages.discard(pkg)
        self._change_count += 1

    def _handle_shell_exec(self, args: dict, output: str) -> None:
        """Extract common env facts from shell command outputs.

        Uses substring matching so compound commands like
        ``whoami && hostname`` or ``echo foo && id`` are handled correctly.
        """
        cmd = (args.get("command") or "").strip().lower()
        out = output.strip()
        if not out or out.startswith("["):
            return

        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        matched = False

        # ── username: whoami / id -un ─────────────────────────────────────
        if "whoami" in cmd or "id -un" in cmd:
            # Find first line that looks like a plain UNIX username
            for ln in lines:
                if re.match(r'^[a-z_][a-z0-9_.\-]*$', ln, re.I) and len(ln) < 64:
                    self.env_facts["current_user"] = ln
                    self._change_count += 1
                    matched = True
                    break

        # ── username from full id output: uid=0(root) gid=0(root) … ──────
        if re.search(r'\bid\b', cmd) and "uid=" in out:
            m = re.search(r'uid=\d+\(([^)]+)\)', out)
            if m:
                self.env_facts["current_user"] = m.group(1)
                self._change_count += 1
                matched = True

        # ── hostname ──────────────────────────────────────────────────────
        if "hostname" in cmd:
            # Scan in reverse: in compound commands like `whoami && hostname`
            # the hostname output is the *last* token, not the first.
            for ln in reversed(lines):
                # skip lines that are clearly not hostnames (contain spaces, =, :)
                if re.match(r'^[a-zA-Z0-9][a-zA-Z0-9.\-]*$', ln) and len(ln) < 128:
                    self.env_facts["hostname"] = ln
                    self._change_count += 1
                    matched = True
                    break

        # ── uname ─────────────────────────────────────────────────────────
        if "uname" in cmd and lines:
            self.env_facts["uname"] = lines[0][:200]
            self._change_count += 1
            matched = True

        # ── ip / ifconfig — extract IPv4 addresses ────────────────────────
        if "ip addr" in cmd or "ip a" in cmd or "ifconfig" in cmd:
            ifaces = re.findall(r"inet (\d{1,3}(?:\.\d{1,3}){3})", out)
            if ifaces:
                non_lo = [ip for ip in ifaces if ip != "127.0.0.1"]
                self.env_facts["local_ips"] = ", ".join(non_lo) if non_lo else ifaces[0]
                self._change_count += 1
                matched = True

        # ── iwconfig / iw dev — WiFi interfaces ───────────────────────────
        if "iwconfig" in cmd or "iw dev" in cmd:
            wlan_ifaces = re.findall(r"(wlan\d+|wlp\w+)", out)
            if wlan_ifaces:
                self.env_facts["wifi_interfaces"] = ", ".join(
                    dict.fromkeys(wlan_ifaces)
                )
                self._change_count += 1
                matched = True

        # ── Generic: store first-line output for short single commands ────
        if not matched and len(out) < 200 and "\n" not in out:
            key = re.sub(r"[^a-z0-9_]", "_", cmd[:40]).strip("_")
            if key:
                self.env_facts[f"cmd_{key}"] = out[:120]
                self._change_count += 1

    def _handle_user_audit(self, _args: dict, output: str) -> None:
        """Extract current user list from user_audit output."""
        # Look for lines matching 'username:x:uid:gid' pattern
        users = re.findall(r"^([a-z_][a-z0-9_-]{0,31}):", output, re.MULTILINE)
        if users:
            self.env_facts["system_users"] = ", ".join(users[:15])
            self._change_count += 1

    def summarize(self, max_chars: int = 1200) -> str:
        """Alias for summary() for API consistency."""
        return self.summary(max_chars)

    # Handler dispatch table
    _HANDLERS: dict[str, Any] = {}


# Build handler table after class definition (avoids forward refs)
WorldState._HANDLERS = {
    "file_read":       WorldState._handle_file_read,
    "file_write":      WorldState._handle_file_write,
    "nmap_scan":       WorldState._handle_nmap,
    "system_status":   WorldState._handle_system_status,
    "service_status":  WorldState._handle_service_status,
    "pkg_install":     WorldState._handle_pkg_install,
    "pkg_remove":      WorldState._handle_pkg_remove,
    "shell_exec":      WorldState._handle_shell_exec,
    "user_audit":      WorldState._handle_user_audit,
}
