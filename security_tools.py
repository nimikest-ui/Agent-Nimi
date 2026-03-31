"""
Security / Pentest Tools - nmap, nikto, gobuster, searchsploit, hydra, enum4linux
"""
import shutil
from .registry import tool
from .shell_tools import shell_exec


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
