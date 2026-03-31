"""Tools package - auto-import all tool modules to register them."""
from .registry import get_tool, list_tools, run_tool, parse_tool_call, list_tool_manifests, discover_tools
from . import shell_tools
from . import security_tools
from . import monitoring_tools
from . import file_pkg_tools
from . import memory_tools
try:
    from . import browser_tools
except Exception as _bt_err:
    import sys
    print(f"  ⚠️ browser_tools not loaded: {_bt_err}", file=sys.stderr)
try:
    from . import osint_tools
except Exception as _ot_err:
    import sys
    print(f"  ⚠️ osint_tools not loaded: {_ot_err}", file=sys.stderr)
from .custom_loader import load_all_custom_tools, create_custom_tool, delete_custom_tool, list_custom_tools

# Load user-defined custom tools from disk
_custom_load_result = load_all_custom_tools()
if _custom_load_result["loaded"] > 0:
    print(f"  \u2705 Loaded {_custom_load_result['loaded']} custom tools")
if _custom_load_result["errors"]:
    for err in _custom_load_result["errors"]:
        print(f"  \u26a0\ufe0f Custom tool error: {err}")

__all__ = [
    "get_tool",
    "list_tools",
    "run_tool",
    "parse_tool_call",
    "list_tool_manifests",
    "discover_tools",
    "create_custom_tool",
    "delete_custom_tool",
    "list_custom_tools",
]
