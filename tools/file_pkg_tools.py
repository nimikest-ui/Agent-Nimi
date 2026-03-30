"""
File & Package Tools - File operations and apt package management
"""
import os
import shutil
import time as _time
from .registry import tool
from .shell_tools import shell_exec

# Track recent file backups for rollback (path → backup_path)
_recent_backups: dict[str, str] = {}


# === File Operations ===

@tool("file_read", "Read contents of a file", manifest={"action_class": "read_only", "capabilities": ["analysis"]})
def file_read(path: str, lines: int = 0) -> str:
    """Read a file, optionally limiting lines."""
    try:
        if not os.path.exists(path):
            return f"[File not found: {path}]"
        if os.path.isdir(path):
            return f"[Path is a directory: {path}]\n" + shell_exec(f"ls -la {path}", timeout=5)

        with open(path, "r", errors="replace") as f:
            if lines and int(lines) > 0:
                content = "".join(f.readline() for _ in range(int(lines)))
            else:
                content = f.read()

        # Truncate very large outputs
        if len(content) > 50000:
            content = content[:50000] + f"\n\n[...truncated, file is {os.path.getsize(path)} bytes]"
        return content if content else "[File is empty]"
    except PermissionError:
        return f"[Permission denied: {path}]"
    except Exception as e:
        return f"[Error reading file: {e}]"


@tool("file_write", "Write content to a file", manifest={"action_class": "reversible", "capabilities": ["code"]})
def file_write(path: str, content: str, append: bool = False) -> str:
    """Write or append to a file. Creates a backup before overwriting."""
    try:
        # Create backup before overwriting (not for append or new files)
        if os.path.exists(path) and not append:
            backup_dir = os.path.join(os.path.expanduser("~"), ".agent-nimi", "backups")
            os.makedirs(backup_dir, exist_ok=True)
            safe_name = path.replace("/", "_").lstrip("_")
            backup_path = os.path.join(backup_dir, f"{safe_name}.bak.{int(_time.time())}")
            try:
                shutil.copy2(path, backup_path)
                _recent_backups[os.path.abspath(path)] = backup_path
            except Exception:
                pass  # best-effort backup; don't block the write

        mode = "a" if append else "w"
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, mode) as f:
            f.write(content)
        action = "appended to" if append else "written to"
        return f"[Content {action} {path} ({len(content)} bytes)]"
    except Exception as e:
        return f"[Error writing file: {e}]"


@tool("file_search", "Search for files by name or content", manifest={"action_class": "read_only", "capabilities": ["analysis"]})
def file_search(pattern: str, path: str = "/", type: str = "name") -> str:
    """Search for files."""
    if type == "content":
        cmd = f"grep -rl '{pattern}' {path} 2>/dev/null | head -50"
    else:
        cmd = f"find {path} -name '*{pattern}*' 2>/dev/null | head -50"
    return shell_exec(cmd, timeout=30)


@tool("file_undo", "Undo the last write to a file by restoring the backup", manifest={"action_class": "reversible", "capabilities": ["code"]})
def file_undo(path: str) -> str:
    """Restore a file from its most recent backup created by file_write."""
    abs_path = os.path.abspath(path)
    backup = _recent_backups.get(abs_path)
    if not backup:
        return f"[No backup available for {path}]"
    if not os.path.exists(backup):
        return f"[Backup file missing: {backup}]"
    try:
        shutil.copy2(backup, abs_path)
        del _recent_backups[abs_path]
        return f"[Restored {path} from backup {os.path.basename(backup)}]"
    except Exception as e:
        return f"[Error restoring file: {e}]"


# === Package Management ===

@tool("pkg_install", "Install packages via apt", manifest={"action_class": "reversible", "capabilities": ["sysadmin"], "trust_tier": "tier_2"})
def pkg_install(packages: str) -> str:
    """Install packages."""
    return shell_exec(f"DEBIAN_FRONTEND=noninteractive apt-get install -y {packages}", timeout=300)


@tool("pkg_remove", "Remove packages via apt", manifest={"action_class": "irreversible", "capabilities": ["sysadmin"], "trust_tier": "tier_2"})
def pkg_remove(packages: str) -> str:
    """Remove packages."""
    return shell_exec(f"apt-get remove -y {packages}", timeout=120)


@tool("pkg_search", "Search for available packages", manifest={"action_class": "read_only", "capabilities": ["sysadmin"]})
def pkg_search(query: str) -> str:
    """Search packages."""
    return shell_exec(f"apt-cache search {query} | head -30", timeout=15)


@tool("pkg_update", "Update package lists and optionally upgrade", manifest={"action_class": "reversible", "capabilities": ["sysadmin"], "trust_tier": "tier_2"})
def pkg_update(upgrade: bool = False) -> str:
    """Update/upgrade packages."""
    cmd = "apt-get update"
    if upgrade:
        cmd += " && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y"
    return shell_exec(cmd, timeout=600)
