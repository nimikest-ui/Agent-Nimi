"""
Custom Tool Loader - Create, save, load, and delete user-defined tools at runtime.

Custom tools are stored as JSON metadata + Python code in ~/.agent-nimi/custom_tools/
"""
import os
import json
import importlib
import traceback
from pathlib import Path
from .registry import _TOOLS, tool, default_manifest

CUSTOM_TOOLS_DIR = Path.home() / ".agent-nimi" / "custom_tools"


def _ensure_dir():
    CUSTOM_TOOLS_DIR.mkdir(parents=True, exist_ok=True)


def create_custom_tool(name: str, description: str, args_schema: list, code: str, manifest: dict | None = None) -> dict:
    """Create and register a custom tool.

    Args:
        name: Tool name (snake_case)
        description: What the tool does
        args_schema: List of {"name": str, "type": str, "required": bool, "default": any}
        code: Python function body. Receives declared args. Must return a string.

    Returns:
        {"success": bool, "message": str}
    """
    _ensure_dir()

    # Validate name
    if not name.isidentifier():
        return {"success": False, "message": f"Invalid tool name: '{name}'. Use snake_case."}
    if name in _TOOLS:
        return {"success": False, "message": f"Tool '{name}' already exists. Delete it first to recreate."}

    # Build the function signature
    param_parts = []
    for arg in args_schema:
        aname = arg["name"]
        atype = arg.get("type", "str")
        if arg.get("required", True):
            param_parts.append(f"{aname}")
        else:
            default = arg.get("default", "None")
            if isinstance(default, str) and atype == "str":
                default = repr(default)
            param_parts.append(f"{aname}={default}")

    params_str = ", ".join(param_parts)

    # Build full function source
    func_source = f"def {name}({params_str}):\n"
    for line in code.split("\n"):
        func_source += f"    {line}\n"

    # Try to compile and execute it
    try:
        exec_globals = {
            "__builtins__": __builtins__,
            "subprocess": __import__("subprocess"),
            "os": __import__("os"),
            "re": __import__("re"),
            "json": __import__("json"),
            "shlex": __import__("shlex"),
            "pathlib": __import__("pathlib"),
            "requests": _safe_import("requests"),
        }
        exec(compile(func_source, f"<custom_tool:{name}>", "exec"), exec_globals)
        func = exec_globals[name]
    except Exception as e:
        return {"success": False, "message": f"Code compilation error: {e}\n{traceback.format_exc()}"}

    # Register in the tool registry
    from .registry import _extract_params
    _TOOLS[name] = {
        "func": func,
        "name": name,
        "description": description,
        "params": _extract_params(func),
        "custom": True,
        "manifest": {**default_manifest(name, description), **(manifest or {})},
    }

    # Save to disk
    meta = {
        "name": name,
        "description": description,
        "args_schema": args_schema,
        "code": code,
        "manifest": manifest or {},
    }
    meta_file = CUSTOM_TOOLS_DIR / f"{name}.json"
    with open(meta_file, "w") as f:
        json.dump(meta, f, indent=2)

    return {"success": True, "message": f"Tool '{name}' created and registered."}


def delete_custom_tool(name: str) -> dict:
    """Delete a custom tool."""
    info = _TOOLS.get(name)
    if not info:
        return {"success": False, "message": f"Tool '{name}' not found."}
    if not info.get("custom"):
        return {"success": False, "message": f"Tool '{name}' is a built-in tool and cannot be deleted."}

    del _TOOLS[name]

    meta_file = CUSTOM_TOOLS_DIR / f"{name}.json"
    if meta_file.exists():
        meta_file.unlink()

    return {"success": True, "message": f"Tool '{name}' deleted."}


def list_custom_tools() -> list[dict]:
    """List all custom tools with their metadata."""
    result = []
    for name, info in _TOOLS.items():
        if info.get("custom"):
            meta_file = CUSTOM_TOOLS_DIR / f"{name}.json"
            meta = {}
            if meta_file.exists():
                with open(meta_file) as f:
                    meta = json.load(f)
            result.append({
                "name": name,
                "description": info["description"],
                "args_schema": meta.get("args_schema", []),
                "code": meta.get("code", ""),
                "manifest": info.get("manifest", meta.get("manifest", {})),
            })
    return result


def load_all_custom_tools():
    """Load all saved custom tools from disk. Called on startup."""
    _ensure_dir()
    loaded = 0
    errors = []
    for meta_file in sorted(CUSTOM_TOOLS_DIR.glob("*.json")):
        try:
            with open(meta_file) as f:
                meta = json.load(f)
            name = meta["name"]
            if name in _TOOLS:
                continue  # Already registered (maybe built-in)
            result = create_custom_tool(
                name=name,
                description=meta["description"],
                args_schema=meta.get("args_schema", []),
                code=meta["code"],
                manifest=meta.get("manifest", {}),
            )
            if result["success"]:
                loaded += 1
            else:
                errors.append(f"{name}: {result['message']}")
        except Exception as e:
            errors.append(f"{meta_file.name}: {e}")
    return {"loaded": loaded, "errors": errors}


def _safe_import(module_name):
    """Import a module or return None if unavailable."""
    try:
        return __import__(module_name)
    except ImportError:
        return None


def refresh_agent_prompt(agent):
    """Rebuild the agent's system message to include current custom tools."""
    from config import SYSTEM_PROMPT
    custom = list_custom_tools()
    if custom:
        extra = "\n\n## Custom Tools (user-created)\n"
        for t in custom:
            args_desc = ", ".join(
                f"`{a['name']}` ({a.get('type','str')})" for a in t.get("args_schema", [])
            ) or "none"
            extra += f"- **{t['name']}**: {t['description']}. Args: {args_desc}\n"
        prompt = SYSTEM_PROMPT + extra
    else:
        prompt = SYSTEM_PROMPT
    agent.messages[0] = {"role": "system", "content": prompt}


# ─── Agent-callable tool wrappers ───
# These are registered with @tool so the LLM can invoke them via JSON during chat

@tool("create_tool", "Create a new custom tool. Write the Python function body that will become the tool. The code receives the declared args and must return a string.")
def agent_create_tool(name: str, description: str, args_json: str = "[]", code: str = "") -> str:
    """Create a new custom tool from chat.

    Args:
        name: snake_case tool name
        description: what the tool does
        args_json: JSON string - array of {"name": str, "type": str, "required": bool}
        code: Python function body - receives declared args, must return a string
    """
    try:
        if isinstance(args_json, list):
            args_schema = args_json
        else:
            args_schema = json.loads(args_json) if args_json else []
    except json.JSONDecodeError as e:
        return f"Error parsing args_json: {e}. Provide a valid JSON array."

    result = create_custom_tool(
        name,
        description,
        args_schema,
        code,
        manifest={
            "capabilities": ["custom"],
            "provider_affinity": "copilot",
            "trust_tier": "tier_1",
            "category": "custom",
        },
    )
    return result["message"]


@tool("delete_tool", "Delete a user-created custom tool by name")
def agent_delete_tool(name: str) -> str:
    """Delete a custom tool."""
    result = delete_custom_tool(name)
    return result["message"]


@tool("list_my_tools", "List all user-created custom tools with their descriptions and code")
def agent_list_tools() -> str:
    """List custom tools."""
    tools = list_custom_tools()
    if not tools:
        return "No custom tools have been created yet."
    lines = []
    for t in tools:
        args_desc = ", ".join(f"{a['name']} ({a.get('type','str')})" for a in t.get("args_schema", [])) or "none"
        lines.append(f"- {t['name']}: {t['description']} | args: {args_desc}")
    return "\n".join(lines)
