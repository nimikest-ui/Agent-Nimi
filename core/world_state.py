"""World-State Tracker (Phase 8 + Phase 12 Graph)
──────────────────────────────────────────────
Maintains a structured model of observed environment facts so the agent
loop can inject a concise summary instead of relying solely on long
message history for grounding.

Phase 12 additions:
  • Typed/labeled graph edges (HAS_PORT, RUNS_SERVICE, HAS_CVE, …)
  • Graph handlers for OSINT tools (whois, CVE, Shodan, web_search)
  • Graph persistence (save/load JSON)
  • Query API (neighbours by type, BFS path, attack surface)
  • Optional NetworkX backend for analytics
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# ── Optional NetworkX backend ─────────────────────────────────────────────────
try:
    import networkx as nx  # type: ignore
    _HAS_NX = True
except ImportError:
    nx = None  # type: ignore
    _HAS_NX = False


# ── Edge type constants ───────────────────────────────────────────────────────
class EdgeType:
    """Well-known edge labels for the world-state graph."""
    SCANNED       = "SCANNED"         # attacker → host
    HAS_PORT      = "HAS_PORT"        # host → port:proto node
    RUNS_SERVICE  = "RUNS_SERVICE"    # port node → service/version
    HAS_CVE       = "HAS_CVE"         # service → CVE node
    RESOLVES_TO   = "RESOLVES_TO"     # domain → IP
    REGISTERED_BY = "REGISTERED_BY"   # domain → registrar
    HAS_DIR       = "HAS_DIR"         # host → discovered directory
    HAS_VULN      = "HAS_VULN"        # host/service → vulnerability
    HAS_EXPLOIT   = "HAS_EXPLOIT"     # CVE/vuln → exploit
    INTEL         = "INTEL"           # host/CVE → web intel node
    LINKED        = "LINKED"          # generic fallback


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
        # Adjacency list: node_id → set of neighbour node_ids
        self.graph: dict[str, set[str]] = {}
        self.graph_labels: dict[str, str] = {}       # node_id → human label
        # Typed edges: (src, dst) → edge_type string (see EdgeType constants)
        self.graph_edge_types: dict[tuple[str, str], str] = {}
        # Optional NetworkX mirror graph (built lazily)
        self._nx_graph: Any = None

    # ── Graph API ─────────────────────────────────────────────────────────

    def add_graph_node(self, node_id: str, label: str = "") -> None:
        """Ensure a node exists in the graph."""
        if node_id not in self.graph:
            self.graph[node_id] = set()
            self._change_count += 1
        if label:
            self.graph_labels[node_id] = label

    def add_graph_edge(
        self,
        src: str,
        dst: str,
        label_src: str = "",
        label_dst: str = "",
        edge_type: str = EdgeType.LINKED,
    ) -> None:
        """Add a directed, typed edge src → dst.  Nodes are created if missing."""
        self.add_graph_node(src, label_src)
        self.add_graph_node(dst, label_dst)
        is_new = dst not in self.graph[src]
        self.graph[src].add(dst)
        self.graph_edge_types[(src, dst)] = edge_type
        if is_new:
            self._change_count += 1
        # Mirror into NetworkX if available
        if _HAS_NX:
            self._ensure_nx()
            if not self._nx_graph.has_edge(src, dst):
                self._nx_graph.add_edge(src, dst, edge_type=edge_type)
            else:
                self._nx_graph[src][dst]["edge_type"] = edge_type

    def get_graph_neighbors(self, node_id: str) -> list[str]:
        """Return all neighbours of *node_id* (empty list if node unknown)."""
        return sorted(self.graph.get(node_id, set()))

    def graph_summary(self, max_edges: int = 12) -> str:
        """Compact adjacency summary for LLM context, now with edge types."""
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
                etype = self.graph_edge_types.get((src, dst), "")
                tag = f" [{etype}]" if etype else ""
                lines.append(f"  {src_label} ─{tag}→ {dst_label}")
                count += 1
                if count >= max_edges:
                    total_edges = sum(len(d) for d in self.graph.values())
                    lines.append(f"  … ({len(self.graph)} nodes, {total_edges} edges total)")
                    break
            if count >= max_edges:
                break
        return "Network graph:\n" + "\n".join(lines) if lines else ""

    # ── Graph queries (Phase 12) ───────────────────────────────────────

    def get_neighbors_by_type(self, node_id: str, edge_type: str) -> list[str]:
        """Return neighbours connected by a specific edge type."""
        return sorted(
            dst for dst in self.graph.get(node_id, set())
            if self.graph_edge_types.get((node_id, dst)) == edge_type
        )

    def get_edge_type(self, src: str, dst: str) -> str:
        """Return the edge type between two nodes, or '' if no edge."""
        return self.graph_edge_types.get((src, dst), "")

    def find_path(self, src: str, dst: str) -> list[str]:
        """BFS shortest path from *src* to *dst*. Returns [] if unreachable."""
        if src == dst:
            return [src]
        if _HAS_NX and self._nx_graph is not None:
            try:
                return list(nx.shortest_path(self._nx_graph, src, dst))
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                return []
        # Native BFS fallback
        visited: set[str] = {src}
        queue: deque[list[str]] = deque([[src]])
        while queue:
            path = queue.popleft()
            for neighbor in self.graph.get(path[-1], set()):
                if neighbor == dst:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])
        return []

    def get_nodes_by_label(self, pattern: str) -> list[str]:
        """Return node IDs whose label matches (case-insensitive substring)."""
        pat = pattern.lower()
        return [
            nid for nid, label in self.graph_labels.items()
            if pat in label.lower()
        ]

    def get_attack_surface(self, host: str) -> dict[str, Any]:
        """Build a summary of everything known about a host from the graph."""
        surface: dict[str, Any] = {
            "host": host, "ports": [], "services": [], "cves": [],
            "vulns": [], "exploits": [], "directories": [], "intel": [],
        }
        for dst in self.graph.get(host, set()):
            etype = self.graph_edge_types.get((host, dst), "")
            label = self.graph_labels.get(dst, dst)
            if etype == EdgeType.HAS_PORT:
                surface["ports"].append(label)
                # Follow port → service → CVE chains
                for svc_dst in self.graph.get(dst, set()):
                    stype = self.graph_edge_types.get((dst, svc_dst), "")
                    slabel = self.graph_labels.get(svc_dst, svc_dst)
                    if stype == EdgeType.RUNS_SERVICE:
                        surface["services"].append(slabel)
                    elif stype == EdgeType.HAS_CVE:
                        surface["cves"].append(slabel)
            elif etype == EdgeType.HAS_CVE:
                surface["cves"].append(label)
            elif etype == EdgeType.HAS_VULN:
                surface["vulns"].append(label)
            elif etype == EdgeType.HAS_DIR:
                surface["directories"].append(label)
            elif etype == EdgeType.INTEL:
                surface["intel"].append(label)
        return surface

    def graph_stats(self) -> dict[str, int]:
        """Return counts for nodes, edges, and edge types."""
        total_edges = sum(len(d) for d in self.graph.values())
        type_counts: dict[str, int] = {}
        for etype in self.graph_edge_types.values():
            type_counts[etype] = type_counts.get(etype, 0) + 1
        return {
            "nodes": len(self.graph),
            "edges": total_edges,
            "edge_types": type_counts,
        }

    # ── Graph persistence (Phase 12) ───────────────────────────────────

    def save_graph(self, path: str | Path) -> None:
        """Persist graph to a JSON file."""
        data = {
            "nodes": {nid: self.graph_labels.get(nid, "") for nid in self.graph},
            "edges": [
                {"src": src, "dst": dst, "type": self.graph_edge_types.get((src, dst), "")}
                for src, dsts in self.graph.items()
                for dst in sorted(dsts)
            ],
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def load_graph(self, path: str | Path) -> bool:
        """Load graph from a JSON file. Returns False if file missing."""
        p = Path(path)
        if not p.exists():
            return False
        with open(p) as f:
            data = json.load(f)
        # Rebuild graph state
        self.graph.clear()
        self.graph_labels.clear()
        self.graph_edge_types.clear()
        self._nx_graph = None
        for nid, label in data.get("nodes", {}).items():
            self.add_graph_node(nid, label)
        for edge in data.get("edges", []):
            self.add_graph_edge(
                edge["src"], edge["dst"],
                edge_type=edge.get("type", EdgeType.LINKED),
            )
        return True

    # ── NetworkX helpers (Phase 12) ────────────────────────────────────

    def _ensure_nx(self) -> None:
        """Lazily build the NetworkX DiGraph mirror."""
        if not _HAS_NX:
            return
        if self._nx_graph is None:
            self._nx_graph = nx.DiGraph()
            for nid in self.graph:
                self._nx_graph.add_node(nid, label=self.graph_labels.get(nid, ""))
            for src, dsts in self.graph.items():
                for dst in dsts:
                    etype = self.graph_edge_types.get((src, dst), "")
                    self._nx_graph.add_edge(src, dst, edge_type=etype)

    @property
    def has_networkx(self) -> bool:
        return _HAS_NX

    def nx_graph(self) -> Any:
        """Return the NetworkX DiGraph (builds lazily). Returns None if nx not installed."""
        if not _HAS_NX:
            return None
        self._ensure_nx()
        return self._nx_graph

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
            "graph_edge_types": {
                f"{src}||{dst}": etype
                for (src, dst), etype in self.graph_edge_types.items()
            },
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
        # ── Graph: host node + typed port/service edges ────────────────
        attacker = self.env_facts.get("local_ips", "attacker").split(",")[0].strip()
        self.add_graph_node(target, label=target)
        self.add_graph_node(attacker, label=f"attacker ({attacker})")
        self.add_graph_edge(attacker, target, edge_type=EdgeType.SCANNED)
        for port_num, svc_name in obs.ports.items():
            port_id = f"{target}:{port_num}"
            self.add_graph_node(port_id, label=f"{port_num}/tcp")
            self.add_graph_edge(target, port_id, edge_type=EdgeType.HAS_PORT)
            if svc_name:
                svc_id = f"svc:{svc_name}@{target}:{port_num}"
                self.add_graph_node(svc_id, label=svc_name)
                self.add_graph_edge(port_id, svc_id, edge_type=EdgeType.RUNS_SERVICE)

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

    # ── OSINT graph handlers (Phase 12) ────────────────────────────────

    def _handle_whois_lookup(self, args: dict, output: str) -> None:
        """Parse whois output and create domain → registrar edges."""
        target = args.get("target", "")
        if not target or not output:
            return
        self.add_graph_node(target, label=f"domain:{target}")
        # Extract registrar
        m = re.search(r"(?:Registrar|registrar).*?:\s*(.+)", output)
        if m:
            registrar = m.group(1).strip()[:80]
            reg_id = f"registrar:{registrar[:40]}"
            self.add_graph_node(reg_id, label=registrar)
            self.add_graph_edge(target, reg_id, edge_type=EdgeType.REGISTERED_BY)
        # Extract name servers → RESOLVES_TO
        for ns in re.findall(r"Name Server:\s*(\S+)", output, re.IGNORECASE):
            ns_lower = ns.lower().rstrip(".")
            self.add_graph_node(ns_lower, label=ns_lower)
            self.add_graph_edge(target, ns_lower, edge_type=EdgeType.RESOLVES_TO)
        self._change_count += 1

    def _handle_cve_lookup(self, args: dict, output: str) -> None:
        """Parse CVE lookup and create CVE nodes linked to the graph."""
        cve_id = args.get("cve_id", "")
        if not cve_id or not output:
            return
        # Extract CVSS score if present
        cvss_match = re.search(r"CVSS.*?([\d.]+)", output)
        score = cvss_match.group(1) if cvss_match else "?"
        label = f"{cve_id} (CVSS {score})"
        self.add_graph_node(cve_id, label=label)
        # Try to link CVE to known hosts/services in the graph
        desc_lower = output.lower()
        for host_id, host_obs in self.hosts.items():
            for port, svc in host_obs.ports.items():
                if svc.lower() in desc_lower:
                    svc_node = f"svc:{svc}@{host_id}:{port}"
                    if svc_node in self.graph:
                        self.add_graph_edge(svc_node, cve_id, edge_type=EdgeType.HAS_CVE)
        self._change_count += 1

    def _handle_shodan_host(self, args: dict, output: str) -> None:
        """Parse Shodan host info into graph nodes."""
        ip = args.get("ip", "")
        if not ip or not output:
            return
        self.add_graph_node(ip, label=ip)
        # Parse ports from Shodan output
        for m in re.finditer(r"Port\s+(\d+).*?(?:Service|Banner)?:?\s*(.*)?", output):
            port = m.group(1)
            svc = (m.group(2) or "").strip()[:40]
            port_id = f"{ip}:{port}"
            self.add_graph_node(port_id, label=f"{port}/tcp")
            self.add_graph_edge(ip, port_id, edge_type=EdgeType.HAS_PORT)
            if svc:
                svc_id = f"svc:{svc}@{ip}:{port}"
                self.add_graph_node(svc_id, label=svc)
                self.add_graph_edge(port_id, svc_id, edge_type=EdgeType.RUNS_SERVICE)
        # Parse hostnames
        for hostname in re.findall(r"Hostname[s]?:\s*(\S+)", output, re.IGNORECASE):
            hostname = hostname.strip().rstrip(",")
            self.add_graph_node(hostname, label=hostname)
            self.add_graph_edge(hostname, ip, edge_type=EdgeType.RESOLVES_TO)
        self._change_count += 1

    def _handle_web_search(self, args: dict, output: str) -> None:
        """Store search intel as a compact node linked to the query context."""
        query = args.get("query", "")
        if not query or not output:
            return
        # Create an intel node summarizing the search
        intel_id = f"intel:search:{hashlib.md5(query.encode(), usedforsecurity=False).hexdigest()[:8]}"
        # Count result lines
        result_count = len([ln for ln in output.splitlines() if ln.strip()])
        self.add_graph_node(intel_id, label=f"search({query[:50]}) [{result_count} results]")
        # Link to any known hosts mentioned in results
        for host_id in self.hosts:
            if host_id in output:
                self.add_graph_edge(host_id, intel_id, edge_type=EdgeType.INTEL)
        self._change_count += 1

    def _handle_github_search(self, args: dict, output: str) -> None:
        """Store GitHub search as intel node."""
        query = args.get("query", "")
        if not query or not output:
            return
        intel_id = f"intel:github:{hashlib.md5(query.encode(), usedforsecurity=False).hexdigest()[:8]}"
        result_count = len([ln for ln in output.splitlines() if ln.strip()])
        self.add_graph_node(intel_id, label=f"github({query[:50]}) [{result_count} results]")
        self._change_count += 1

    def _handle_searchsploit(self, args: dict, output: str) -> None:
        """Link searchsploit results as exploit nodes."""
        query = args.get("query", "")
        if not query or not output:
            return
        # Each exploit line typically has "Title | Path"
        exploits = re.findall(r"^(.+?)\s*\|\s*(exploits/.+)$", output, re.MULTILINE)
        for title, path in exploits[:5]:  # cap at 5 to avoid flooding
            exploit_id = f"exploit:{path.strip()}"
            self.add_graph_node(exploit_id, label=title.strip()[:80])
            # Try to link to known CVEs
            cve_in_title = re.search(r"(CVE-\d{4}-\d{4,7})", title, re.IGNORECASE)
            if cve_in_title:
                cve_id = cve_in_title.group(1).upper()
                if cve_id in self.graph:
                    self.add_graph_edge(cve_id, exploit_id, edge_type=EdgeType.HAS_EXPLOIT)
        self._change_count += 1

    def _handle_gobuster_scan(self, args: dict, output: str) -> None:
        """Add discovered directories/files to the graph."""
        target = args.get("target", "")
        if not target or not output:
            return
        # Normalize target to host node
        host = re.sub(r"^https?://", "", target).split("/")[0].split(":")[0]
        self.add_graph_node(host, label=host)
        for m in re.finditer(r"/(\S+)\s+\(Status:\s*(\d+)\)", output):
            dir_path, status = m.group(1), m.group(2)
            if status.startswith(("2", "3")):  # 2xx, 3xx
                dir_id = f"dir:{host}/{dir_path}"
                self.add_graph_node(dir_id, label=f"/{dir_path} [{status}]")
                self.add_graph_edge(host, dir_id, edge_type=EdgeType.HAS_DIR)
        self._change_count += 1

    def _handle_nikto_scan(self, args: dict, output: str) -> None:
        """Add Nikto vulnerability findings to the graph."""
        target = args.get("target", "")
        if not target or not output:
            return
        host = re.sub(r"^https?://", "", target).split("/")[0].split(":")[0]
        self.add_graph_node(host, label=host)
        # Nikto findings: "+ OSVDB-XXXX: /path: description"
        for i, m in enumerate(re.finditer(r"\+\s+(OSVDB-\d+|\w+):\s+(.+)", output)):
            if i >= 8:  # cap
                break
            vuln_code, desc = m.group(1), m.group(2).strip()[:80]
            vuln_id = f"vuln:{vuln_code}@{host}"
            self.add_graph_node(vuln_id, label=f"{vuln_code}: {desc}")
            self.add_graph_edge(host, vuln_id, edge_type=EdgeType.HAS_VULN)
        self._change_count += 1

    def summarize(self, max_chars: int = 1200) -> str:
        """Alias for summary() for API consistency."""
        return self.summary(max_chars)

    # Handler dispatch table
    _HANDLERS: dict[str, Any] = {}


# Build handler table after class definition (avoids forward refs)
WorldState._HANDLERS = {
    "file_read":          WorldState._handle_file_read,
    "file_write":         WorldState._handle_file_write,
    "nmap_scan":          WorldState._handle_nmap,
    "system_status":      WorldState._handle_system_status,
    "service_status":     WorldState._handle_service_status,
    "pkg_install":        WorldState._handle_pkg_install,
    "pkg_remove":         WorldState._handle_pkg_remove,
    "shell_exec":         WorldState._handle_shell_exec,
    "user_audit":         WorldState._handle_user_audit,
    "browser_screenshot": WorldState._handle_browser_screenshot,
    # OSINT handlers
    "whois_lookup":       WorldState._handle_whois_lookup,
    "cve_lookup":         WorldState._handle_cve_lookup,
    "shodan_host":        WorldState._handle_shodan_host,
    "web_search":         WorldState._handle_web_search,
    "github_search":      WorldState._handle_github_search,
    "searchsploit":       WorldState._handle_searchsploit,
    # Security tool handlers
    "gobuster_scan":      WorldState._handle_gobuster_scan,
    "nikto_scan":         WorldState._handle_nikto_scan,
}
