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

    Phase 12 addition: graph adjacency list for host/service relationships.
    """

    def __init__(self) -> None:
        self.files: dict[str, FileObservation] = {}
        self.hosts: dict[str, HostObservation] = {}
        self.services: dict[str, str] = {}          # service_name → status
        self.packages: set[str] = set()
        self.env_facts: dict[str, str] = {}          # key → value misc facts
        self._change_count: int = 0
        # ── Graph layer (Phase 12) ────────────────────────────────────────
        # Pure-dict adjacency list: node_id → set of neighbour node_ids
        # Node IDs are typically host IPs, service names, or "user:<name>"
        self.graph: dict[str, set[str]] = {}
        self.graph_labels: dict[str, str] = {}       # node_id → human label

    # ── Graph API ─────────────────────────────────────────────────────────

    def add_graph_node(self, node_id: str, label: str = "") -> None:
        """Ensure a node exists in the graph."""
        if node_id not in self.graph:
            self.graph[node_id] = set()
            self._change_count += 1
        if label:
            self.graph_labels[node_id] = label

    def add_graph_edge(self, src: str, dst: str, label_src: str = "", label_dst: str = "") -> None:
        """Add a directed edge src → dst.  Nodes are created if they don't exist."""
        self.add_graph_node(src, label_src)
        self.add_graph_node(dst, label_dst)
        if dst not in self.graph[src]:
            self.graph[src].add(dst)
            self._change_count += 1

    def get_graph_neighbors(self, node_id: str) -> list[str]:
        """Return all neighbours of *node_id* (empty list if node unknown)."""
        return sorted(self.graph.get(node_id, set()))

    def graph_summary(self, max_edges: int = 12) -> str:
        """Compact adjacency summary for LLM context."""
        if not self.graph:
            return ""
        lines: list[str] = []
        count = 0
        for src, dsts in sorted(self.graph.items()):
            if not dsts:
                continue
            src_label = self.graph_labels.get(src, src)
            for dst in sorted(dsts):
                dst_label = self.graph_labels.get(dst, dst)
                lines.append(f"  {src_label} → {dst_label}")
                count += 1
                if count >= max_edges:
                    lines.append(f"  ... ({len(self.graph)} nodes total)")
                    break
            if count >= max_edges:
                break
        return "Network graph:\n" + "\n".join(lines) if lines else ""

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

        # WiFi monitor mode — surfaced first so LLM always knows the correct interface name
        mon_active = self.env_facts.get("wifi_monitor_active", "")
        mon_ifaces = self.env_facts.get("wifi_monitor_interfaces", "")
        killed_procs = self.env_facts.get("airmon_killed_procs", "")
        if mon_active or mon_ifaces:
            wifi_line = (
                f"*** WiFi MONITOR MODE ACTIVE — use interface '{mon_active or mon_ifaces}'"
                " with airodump-ng / aireplay-ng / aircrack-ng ***"
            )
            if killed_procs:
                wifi_line += (
                    f" | killed by airmon-ng: {killed_procs}"
                    " (run wifi_monitor_stop or network_reconnect to restore internet)"
                )
            parts.append(wifi_line)

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

        graph_str = self.graph_summary()
        if graph_str:
            parts.append(graph_str)

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
            "graph": {k: sorted(v) for k, v in self.graph.items()},
            "graph_labels": dict(self.graph_labels),
        }

    # ── Internal handlers per tool ────────────────────────────────────────

    def _handle_file_read(self, args: dict, output: str) -> None:
        path = args.get("path", "")
        if not path or output.startswith("["):
            return
        self.files[path] = FileObservation(
            path=path,
            size=len(output),
            content_hash=hashlib.md5(output[:2000].encode(), usedforsecurity=False).hexdigest(),
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
                content_hash=hashlib.md5(content[:2000].encode(), usedforsecurity=False).hexdigest(),
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
        # ── Graph: add host node + edges from attacker ────────────────────
        attacker = self.env_facts.get("local_ips", "attacker").split(",")[0].strip()
        self.add_graph_node(target, label=target)
        self.add_graph_node(attacker, label=f"attacker ({attacker})")
        if obs.ports:
            self.add_graph_edge(attacker, target, label_dst=target)

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

        # ── airmon-ng — WiFi monitor mode tracking ────────────────────────
        # This is the critical block: when airmon-ng is used, the interface
        # may keep its original name (wlan1) or get renamed (wlan1mon).
        # We track the actual monitor interface name regardless.
        if "airmon-ng" in cmd:
            matched = True

            # airmon-ng check kill → record which services were killed
            # so the watchdog / restore logic knows what to bring back up.
            if "check kill" in cmd:
                killed = re.findall(
                    r"\d+\s+(wpa_supplicant|NetworkManager|dhclient|wpa_cli|hostapd)",
                    out,
                )
                if killed:
                    self.env_facts["airmon_killed_procs"] = ", ".join(
                        dict.fromkeys(killed)
                    )
                    self._change_count += 1

            # airmon-ng start <iface> → detect the monitor mode interface name.
            # The output can say:
            #   "monitor mode vif enabled on phy0/wlan1mon"
            #   "monitor mode vif enabled for [phy0]wlan1 on [phy0]wlan1mon"
            #   "monitor mode enabled"  (name unchanged)
            if "start" in cmd:
                # Try to parse the resulting monitor interface from output
                m_iface = re.search(
                    r"monitor mode.*?(?:for\s+\[?\w+\]?\w+\s+on\s+\[?\w+\]?|on\s+(?:phy\w+/)?)([a-zA-Z0-9_]+)",
                    out, re.IGNORECASE,
                )
                if m_iface:
                    mon_iface = m_iface.group(1).strip()
                else:
                    # Fallback: assume the driver kept the same name as the arg
                    m_cmd = re.search(r"airmon-ng\s+start\s+(\S+)", cmd)
                    mon_iface = m_cmd.group(1) if m_cmd else ""

                if mon_iface:
                    # Track current set of monitor interfaces
                    existing = self.env_facts.get("wifi_monitor_interfaces", "")
                    ifaces = set(x for x in existing.split(", ") if x)
                    ifaces.add(mon_iface)
                    self.env_facts["wifi_monitor_interfaces"] = ", ".join(sorted(ifaces))

                    # Also map original → monitor name for the LLM to query
                    m_orig = re.search(r"airmon-ng\s+start\s+(\S+)", cmd)
                    if m_orig:
                        orig_iface = m_orig.group(1)
                        self.env_facts[f"wifi_monitor_of_{orig_iface}"] = mon_iface
                        # Canonical: what name to use with airodump-ng / aireplay-ng
                        self.env_facts["wifi_monitor_active"] = mon_iface
                    self._change_count += 1

            # airmon-ng stop <iface> → remove from monitor tracking
            if "stop" in cmd:
                m_stop = re.search(r"airmon-ng\s+stop\s+(\S+)", cmd)
                if m_stop:
                    stopped = m_stop.group(1)
                    existing = self.env_facts.get("wifi_monitor_interfaces", "")
                    ifaces = set(x for x in existing.split(", ") if x)
                    ifaces.discard(stopped)
                    if ifaces:
                        self.env_facts["wifi_monitor_interfaces"] = ", ".join(sorted(ifaces))
                    else:
                        self.env_facts.pop("wifi_monitor_interfaces", None)
                        self.env_facts.pop("wifi_monitor_active", None)
                    self.env_facts.pop(f"wifi_monitor_of_{stopped}", None)
                    self._change_count += 1

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

    def _handle_browser_screenshot(self, args: dict, output: str) -> None:
        """Record that a browser screenshot was taken and note the session."""
        sid = args.get("session_id", "?")
        # We can't decode the image here, but we record its existence
        if output.startswith("data:image"):
            self.env_facts[f"browser_screenshot_{sid}"] = f"captured ({len(output)} bytes b64)"
            self._change_count += 1

    def summarize(self, max_chars: int = 1200) -> str:
        """Alias for summary() for API consistency."""
        return self.summary(max_chars)

    # Handler dispatch table
    _HANDLERS: dict[str, Any] = {}


# Build handler table after class definition (avoids forward refs)
WorldState._HANDLERS = {
    "file_read":         WorldState._handle_file_read,
    "file_write":        WorldState._handle_file_write,
    "nmap_scan":         WorldState._handle_nmap,
    "system_status":     WorldState._handle_system_status,
    "service_status":    WorldState._handle_service_status,
    "pkg_install":       WorldState._handle_pkg_install,
    "pkg_remove":        WorldState._handle_pkg_remove,
    "shell_exec":        WorldState._handle_shell_exec,
    "user_audit":        WorldState._handle_user_audit,
    "browser_screenshot": WorldState._handle_browser_screenshot,
}
