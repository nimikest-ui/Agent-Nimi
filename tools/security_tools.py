"""
Security / Pentest Tools - nmap, nikto, gobuster, searchsploit, hydra, enum4linux,
                           wifi monitor mode (airmon-ng / airodump-ng)
"""
import re
import shutil
import subprocess
import time
from .registry import tool
from .shell_tools import shell_exec, _ping_check, _restore_network


def _check_tool(name: str) -> str | None:
    """Check if a tool is installed."""
    if not shutil.which(name):
        return f"[Error: '{name}' is not installed. Run: apt install {name}]"
    return None


@tool("nmap_scan", "Run an nmap scan against a target", manifest={"action_class": "dangerous", "capabilities": ["scan", "recon"], "trust_tier": "tier_2", "provider_affinity": "grok"})
def nmap_scan(target: str, scan_type: str = "quick", ports: str = "", extra_args: str = "") -> str:
    """Run nmap with various scan profiles."""
    err = _check_tool("nmap")
    if err:
        return err

    scan_flags = {
        "quick": "-sV -T4 --top-ports 1000",
        "full": "-sV -sC -p- -T4",
        "vuln": "-sV --script vuln",
        "stealth": "-sS -T2 -f --data-length 24",
        "udp": "-sU -T4 --top-ports 200",
    }

    flags = scan_flags.get(scan_type, scan_flags["quick"])
    if ports:
        flags += f" -p {ports}"
    if extra_args:
        flags += f" {extra_args}"

    cmd = f"nmap {flags} {target}"
    return f"[Running: {cmd}]\n\n" + shell_exec(cmd, timeout=600)


@tool("nikto_scan", "Run nikto web vulnerability scanner", manifest={"action_class": "dangerous", "capabilities": ["scan", "web"], "trust_tier": "tier_2", "provider_affinity": "grok"})
def nikto_scan(target: str, extra_args: str = "") -> str:
    """Run nikto against a web target."""
    err = _check_tool("nikto")
    if err:
        return err

    cmd = f"nikto -h {target} -C all {extra_args}"
    return f"[Running: {cmd}]\n\n" + shell_exec(cmd, timeout=600)


@tool("gobuster_scan", "Run gobuster directory brute-force", manifest={"action_class": "dangerous", "capabilities": ["scan", "web"], "trust_tier": "tier_2", "provider_affinity": "grok"})
def gobuster_scan(target: str, wordlist: str = "/usr/share/wordlists/dirb/common.txt", extra_args: str = "") -> str:
    """Run gobuster for directory enumeration."""
    err = _check_tool("gobuster")
    if err:
        return err

    cmd = f"gobuster dir -u {target} -w {wordlist} -t 50 {extra_args}"
    return f"[Running: {cmd}]\n\n" + shell_exec(cmd, timeout=600)


@tool("searchsploit", "Search ExploitDB for exploits", manifest={"action_class": "read_only", "capabilities": ["recon"], "trust_tier": "tier_2", "provider_affinity": "grok"})
def searchsploit(query: str) -> str:
    """Search exploitdb using searchsploit."""
    err = _check_tool("searchsploit")
    if err:
        return err

    cmd = f"searchsploit {query}"
    return shell_exec(cmd, timeout=30)


@tool("hydra_bruteforce", "Run hydra for brute-force attacks", manifest={"action_class": "dangerous", "capabilities": ["exploit", "password"], "trust_tier": "tier_2", "provider_affinity": "grok"})
def hydra_bruteforce(target: str, service: str, userlist: str, passlist: str, extra_args: str = "") -> str:
    """Run hydra brute-force."""
    err = _check_tool("hydra")
    if err:
        return err

    cmd = f"hydra -L {userlist} -P {passlist} {target} {service} {extra_args}"
    return f"[Running: {cmd}]\n\n" + shell_exec(cmd, timeout=600)


@tool("enum4linux", "Run enum4linux for SMB/NetBIOS enumeration", manifest={"action_class": "dangerous", "capabilities": ["scan", "recon"], "trust_tier": "tier_2", "provider_affinity": "grok"})
def enum4linux_scan(target: str, extra_args: str = "") -> str:
    """Run enum4linux."""
    # Try enum4linux-ng first, fallback to enum4linux
    tool_name = "enum4linux-ng" if shutil.which("enum4linux-ng") else "enum4linux"
    err = _check_tool(tool_name)
    if err:
        return err

    cmd = f"{tool_name} -a {target} {extra_args}"
    return f"[Running: {cmd}]\n\n" + shell_exec(cmd, timeout=300)


# ── WiFi / Aircrack-ng tools ──────────────────────────────────────────────────

def _detect_monitor_interface(base_iface: str, airmon_output: str) -> str:
    """Parse airmon-ng output to find the resulting monitor interface name.

    Some drivers rename wlan1 → wlan1mon; others keep the original name.
    Falls back to base_iface if no rename is detected.
    """
    # Pattern: "monitor mode vif enabled for [phy0]wlan1 on [phy0]wlan1mon"
    m = re.search(
        r"monitor mode.*?on\s+\[?\w*\]?([a-zA-Z0-9_]+)",
        airmon_output, re.IGNORECASE,
    )
    if m:
        candidate = m.group(1).strip()
        if candidate and candidate != base_iface:
            return candidate

    # Pattern: "monitor mode vif enabled on phy0/wlan1mon"
    m2 = re.search(r"phy\w+/([a-zA-Z0-9_]+)", airmon_output)
    if m2:
        return m2.group(1)

    # Check if a *mon variant actually exists in the kernel
    mon_guess = base_iface + "mon"
    try:
        result = subprocess.run(
            ["ip", "link", "show", mon_guess],
            capture_output=True, timeout=3,
        )
        if result.returncode == 0:
            return mon_guess
    except Exception:
        pass

    # Driver kept the original name
    return base_iface


@tool(
    name="wifi_monitor_start",
    description=(
        "Put a WiFi interface into monitor mode using airmon-ng. "
        "Handles airmon-ng check kill automatically, detects the resulting monitor "
        "interface name (even if the driver keeps the original name like wlan1 rather "
        "than renaming to wlan1mon), and records it in agent memory. "
        "Returns the monitor interface name to use with wifi_capture."
    ),
    manifest={
        "action_class": "dangerous",
        "capabilities": ["wifi", "recon"],
        "trust_tier": "tier_2",
        "provider_affinity": "grok",
    },
)
def wifi_monitor_start(interface: str = "wlan1") -> str:
    """Enable monitor mode on a WiFi interface and return the monitor interface name."""
    for tool_bin in ("airmon-ng", "iw"):
        err = _check_tool(tool_bin)
        if err:
            return err

    lines: list[str] = []

    # Step 1: kill interfering processes
    lines.append("[Step 1] Killing interfering processes (airmon-ng check kill)")
    kill_out = shell_exec(f"airmon-ng check kill", timeout=20)
    lines.append(kill_out)

    # Step 2: start monitor mode
    lines.append(f"\n[Step 2] Starting monitor mode on {interface}")
    start_out = shell_exec(f"airmon-ng start {interface}", timeout=20)
    lines.append(start_out)

    # Step 3: detect the actual monitor interface name
    mon_iface = _detect_monitor_interface(interface, start_out)

    # Step 4: verify the interface exists and is in Monitor mode
    lines.append(f"\n[Step 3] Verifying {mon_iface} is in monitor mode")
    iw_out = shell_exec(f"iw dev {mon_iface} info 2>/dev/null || iwconfig {mon_iface} 2>/dev/null", timeout=10)
    lines.append(iw_out)

    in_monitor = "monitor" in iw_out.lower() or "Monitor" in iw_out
    if not in_monitor:
        # Some drivers: check if the original interface is now in monitor mode
        iw_orig = shell_exec(f"iw dev {interface} info 2>/dev/null", timeout=5)
        if "monitor" in iw_orig.lower():
            mon_iface = interface
            in_monitor = True

    status = "READY" if in_monitor else "WARNING: could not confirm monitor mode"
    lines.append(
        f"\n{'='*55}\n"
        f"Monitor interface : {mon_iface}\n"
        f"Status            : {status}\n"
        f"Use this interface with wifi_capture or airodump-ng / aireplay-ng.\n"
        f"{'='*55}"
    )
    return "\n".join(lines)


@tool(
    name="wifi_capture",
    description=(
        "Run airodump-ng to capture WiFi handshakes on a specific BSSID and channel. "
        "Automatically uses the correct monitor interface name (handles wlan1 vs wlan1mon). "
        "Writes capture to the specified output file prefix. "
        "Run wifi_monitor_start first to put the interface in monitor mode."
    ),
    manifest={
        "action_class": "dangerous",
        "capabilities": ["wifi", "recon", "capture"],
        "trust_tier": "tier_2",
        "provider_affinity": "grok",
    },
)
def wifi_capture(
    monitor_interface: str,
    bssid: str,
    channel: int,
    output_file: str = "/tmp/capture",
    duration: int = 60,
) -> str:
    """Capture WiFi traffic with airodump-ng on the specified monitor interface."""
    err = _check_tool("airodump-ng")
    if err:
        return err

    # Verify the interface exists before running
    iw_check = subprocess.run(
        ["ip", "link", "show", monitor_interface],
        capture_output=True, timeout=5,
    )
    if iw_check.returncode != 0:
        return (
            f"[wifi_capture] Interface '{monitor_interface}' does not exist.\n"
            f"Did you run wifi_monitor_start first?\n"
            f"Run: wifi_monitor_start interface=wlan1  to enable monitor mode and get the correct interface name."
        )

    cmd = (
        f"timeout {duration} airodump-ng "
        f"-c {channel} --bssid {bssid} "
        f"{monitor_interface} -w {output_file} --output-format pcap"
    )
    out = shell_exec(cmd, timeout=duration + 10)
    return f"[wifi_capture] Ran for {duration}s on {monitor_interface}\nOutput file prefix: {output_file}\n\n{out}"


@tool(
    name="wifi_monitor_stop",
    description=(
        "Stop monitor mode on a WiFi interface and restore NetworkManager / wpa_supplicant "
        "so internet connectivity returns. Always run this after a WiFi capture session."
    ),
    manifest={
        "action_class": "dangerous",
        "capabilities": ["wifi", "sysadmin"],
        "trust_tier": "tier_2",
        "provider_affinity": "grok",
    },
)
def wifi_monitor_stop(monitor_interface: str = "wlan1mon") -> str:
    """Stop monitor mode and restore networking."""
    lines: list[str] = []

    lines.append(f"[Step 1] Stopping monitor mode on {monitor_interface}")
    stop_out = shell_exec(f"airmon-ng stop {monitor_interface}", timeout=20)
    lines.append(stop_out)

    lines.append("\n[Step 2] Restoring NetworkManager")
    restore_out = _restore_network()
    lines.append(restore_out)

    lines.append("\n[Step 3] Checking connectivity")
    ok = _ping_check(["1.1.1.1", "8.8.8.8"])
    lines.append(f"Internet: {'RESTORED' if ok else 'STILL DOWN — try: systemctl restart NetworkManager'}")
    return "\n".join(lines)
