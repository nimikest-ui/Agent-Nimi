"""
Monitoring Tools - System status, processes, network, logs, disk, user audit
"""
import os
from .registry import tool
from .shell_tools import shell_exec


@tool("system_status", "Get full system status: CPU, RAM, disk, network, uptime", manifest={"action_class": "read_only", "capabilities": ["analysis", "sysadmin"]})
def system_status() -> str:
    """Comprehensive system status overview."""
    sections = []

    # Hostname & uptime
    sections.append("=== SYSTEM INFO ===")
    sections.append(shell_exec("hostname && uname -a && uptime", timeout=5))

    # CPU
    sections.append("\n=== CPU ===")
    sections.append(shell_exec(
        "echo 'Load Average:' && cat /proc/loadavg && echo '' && "
        "echo 'CPU Usage:' && top -bn1 | head -5",
        timeout=10
    ))

    # Memory
    sections.append("\n=== MEMORY ===")
    sections.append(shell_exec("free -h", timeout=5))

    # Disk
    sections.append("\n=== DISK ===")
    sections.append(shell_exec("df -h --total | grep -E '(Filesystem|/dev/|total)'", timeout=5))

    # Network interfaces
    sections.append("\n=== NETWORK ===")
    sections.append(shell_exec("ip -br addr", timeout=5))

    # Top 5 processes
    sections.append("\n=== TOP PROCESSES (CPU) ===")
    sections.append(shell_exec("ps aux --sort=-%cpu | head -6", timeout=5))

    return "\n".join(sections)


@tool("process_list", "List top processes sorted by CPU or memory", manifest={"action_class": "read_only", "capabilities": ["analysis", "sysadmin"]})
def process_list(sort_by: str = "cpu", limit: int = 20) -> str:
    """List top processes."""
    sort_flag = "-%cpu" if sort_by == "cpu" else "-%mem"
    return shell_exec(f"ps aux --sort={sort_flag} | head -{int(limit) + 1}", timeout=10)


@tool("network_connections", "Show active network connections", manifest={"action_class": "read_only", "capabilities": ["analysis", "sysadmin"]})
def network_connections(filter: str = "all") -> str:
    """Show network connections."""
    filters = {
        "listening": "-tlnp",
        "established": "-tnp | grep ESTABLISHED",
        "all": "-tunap",
    }
    flag = filters.get(filter, filters["all"])
    if "|" in flag:
        return shell_exec(f"ss {flag}", timeout=10)
    return shell_exec(f"ss {flag}", timeout=10)


@tool("service_status", "Check systemd service status", manifest={"action_class": "read_only", "capabilities": ["sysadmin"]})
def service_status(service: str) -> str:
    """Check a systemd service."""
    return shell_exec(f"systemctl status {service} --no-pager -l", timeout=10)


@tool("log_view", "View system logs from various sources", manifest={"action_class": "read_only", "capabilities": ["analysis", "sysadmin"]})
def log_view(log_source: str = "syslog", lines: int = 50, filter: str = "", file_path: str = "") -> str:
    """View logs from different sources."""
    lines = int(lines)
    
    if log_source == "journal":
        cmd = f"journalctl --no-pager -n {lines}"
        if filter:
            cmd += f" | grep -i '{filter}'"
    elif log_source == "syslog":
        cmd = f"tail -n {lines} /var/log/syslog 2>/dev/null || journalctl --no-pager -n {lines}"
        if filter:
            cmd += f" | grep -i '{filter}'"
    elif log_source == "auth":
        cmd = f"tail -n {lines} /var/log/auth.log 2>/dev/null || journalctl --no-pager -n {lines} -u ssh"
        if filter:
            cmd += f" | grep -i '{filter}'"
    elif log_source == "dmesg":
        cmd = f"dmesg --time-format iso | tail -n {lines}"
        if filter:
            cmd += f" | grep -i '{filter}'"
    elif log_source == "file" and file_path:
        cmd = f"tail -n {lines} {file_path}"
        if filter:
            cmd += f" | grep -i '{filter}'"
    else:
        return f"Invalid log_source: {log_source}. Use: syslog, auth, journal, dmesg, file"

    return shell_exec(cmd, timeout=15)


@tool("disk_usage", "Show disk usage for a path", manifest={"action_class": "read_only", "capabilities": ["analysis", "sysadmin"]})
def disk_usage(path: str = "/") -> str:
    """Show disk usage."""
    result = shell_exec(f"df -h {path} && echo '' && du -sh {path}/* 2>/dev/null | sort -rh | head -20", timeout=15)
    return result


@tool("user_audit", "Audit system users, sudo access, and recent logins", manifest={"action_class": "read_only", "capabilities": ["analysis", "sysadmin"]})
def user_audit() -> str:
    """Audit users and access."""
    sections = []

    sections.append("=== SYSTEM USERS (with shell) ===")
    sections.append(shell_exec("cat /etc/passwd | grep -v nologin | grep -v /false", timeout=5))

    sections.append("\n=== SUDO USERS ===")
    sections.append(shell_exec("getent group sudo 2>/dev/null || getent group wheel 2>/dev/null", timeout=5))

    sections.append("\n=== RECENT LOGINS ===")
    sections.append(shell_exec("last -n 15 2>/dev/null || echo 'last command not available'", timeout=5))

    sections.append("\n=== CURRENTLY LOGGED IN ===")
    sections.append(shell_exec("w", timeout=5))

    sections.append("\n=== FAILED LOGIN ATTEMPTS ===")
    sections.append(shell_exec("lastb -n 10 2>/dev/null || echo 'lastb not available or no failed logins'", timeout=5))

    return "\n".join(sections)
