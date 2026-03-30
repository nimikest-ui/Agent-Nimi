"""
Tool Registry - Base class and decorator for all agent tools
"""
import json
import functools
from typing import Callable, Any

_TOOLS: dict[str, dict] = {}

# ── Action classification for safety & reversibility ──────────────────────────
ACTION_CLASSES = {
    "read_only":    0,  # observe only, no side effects
    "reversible":   1,  # can be undone (file_write with backup, pkg_install)
    "irreversible": 2,  # hard to undo (shell_exec, rm, pkg_remove)
    "dangerous":    3,  # legal / security implications (nmap, hydra, nikto)
}


def default_manifest(name: str, description: str = "") -> dict:
    """Return a baseline manifest for tools lacking explicit metadata."""
    return {
        "name": name,
        "description": description,
        "capabilities": [],
        "provider_affinity": "any",
        "trust_tier": "tier_1",
        "category": "general",
        "action_class": "read_only",
    }


def tool(name: str, description: str = "", manifest: dict | None = None):
    """Decorator to register a function as an agent tool."""
    def decorator(func: Callable) -> Callable:
        merged_manifest = default_manifest(name, description)
        if manifest:
            merged_manifest.update(manifest)
        _TOOLS[name] = {
            "func": func,
            "name": name,
            "description": description,
            "params": _extract_params(func),
            "manifest": merged_manifest,
        }
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator


def _extract_params(func: Callable) -> dict:
    """Extract parameter info from function annotations."""
    import inspect
    sig = inspect.signature(func)
    params = {}
    for pname, param in sig.parameters.items():
        pinfo = {"required": param.default is inspect.Parameter.empty}
        if param.annotation is not inspect.Parameter.empty:
            pinfo["type"] = param.annotation.__name__ if hasattr(param.annotation, "__name__") else str(param.annotation)
        if param.default is not inspect.Parameter.empty:
            pinfo["default"] = param.default
        params[pname] = pinfo
    return params


def get_tool(name: str) -> dict | None:
    """Get a tool by name."""
    return _TOOLS.get(name)


def list_tools() -> list[str]:
    """List all registered tool names."""
    return list(_TOOLS.keys())


def list_tool_manifests() -> list[dict]:
    """Return manifest records for all registered tools."""
    manifests = []
    for name, info in _TOOLS.items():
        mf = dict(info.get("manifest") or default_manifest(name, info.get("description", "")))
        mf["custom"] = bool(info.get("custom", False))
        mf["params"] = info.get("params", {})
        manifests.append(mf)
    return manifests


def discover_tools(capability: str = "", trust_tier: str = "", provider_affinity: str = "") -> list[dict]:
    """Find tools by manifest filters for router/decomposer consumption."""
    capability = (capability or "").strip().lower()
    trust_tier = (trust_tier or "").strip().lower()
    provider_affinity = (provider_affinity or "").strip().lower()

    matches = []
    for name, info in _TOOLS.items():
        manifest = dict(info.get("manifest") or default_manifest(name, info.get("description", "")))
        caps = [str(c).lower() for c in (manifest.get("capabilities") or [])]
        tier = str(manifest.get("trust_tier", "tier_1")).lower()
        affinity = str(manifest.get("provider_affinity", "any")).lower()

        if capability and capability not in caps:
            continue
        if trust_tier and tier != trust_tier:
            continue
        if provider_affinity and affinity not in {provider_affinity, "any"}:
            continue

        matches.append(
            {
                "name": name,
                "description": info.get("description", ""),
                "custom": bool(info.get("custom", False)),
                "params": info.get("params", {}),
                "manifest": manifest,
            }
        )

    return matches


def run_tool(name: str, args: dict) -> dict:
    """Execute a tool by name with given args. Returns {"success": bool, "output": str}."""
    tool_info = _TOOLS.get(name)
    if not tool_info:
        return {"success": False, "output": f"Unknown tool: {name}. Available: {list_tools()}"}
    try:
        result = tool_info["func"](**args)
        return {"success": True, "output": str(result)}
    except Exception as e:
        return {"success": False, "output": f"Tool '{name}' error: {type(e).__name__}: {e}"}


def parse_tool_call(text: str) -> dict | None:
    """Try to parse a tool call JSON from LLM response text.
    
    Looks for properly marked tool calls only:
    - Direct JSON as the entire response
    - JSON in ```json code blocks
    - JSON after explicit TOOL_CALL: marker
    
    Rejects embedded JSON in narrative text to avoid hallucinated tool calls.
    Returns dict with 'tool' and 'args', or None.
    """
    text = text.strip()
    if not text:
        return None
    
    import re

    # Strategy 0: Response STARTS with a tool-call JSON object.
    # This handles the common case where the LLM outputs:
    #   {"tool":"x","args":{...}}{"tool":"y",...}Some text...
    # We extract only the FIRST balanced JSON object.
    stripped_text = text.lstrip()
    if stripped_text.startswith('{'):
        extracted = _extract_balanced_json(stripped_text, 0)
        if extracted:
            try:
                data = json.loads(extracted)
                if isinstance(data, dict) and "tool" in data:
                    return {"tool": data["tool"], "args": data.get("args", {})}
            except json.JSONDecodeError:
                pass

    # Strategy 1: If the entire response is just JSON, parse it
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "tool" in data:
            return {"tool": data["tool"], "args": data.get("args", {})}
    except json.JSONDecodeError:
        pass

    # Strategy 2: Look for explicit TOOL_CALL: marker
    tool_call_marker = re.search(r'TOOL_CALL:\s*(\{.*\})', text, re.DOTALL)
    if tool_call_marker:
        try:
            data = json.loads(tool_call_marker.group(1))
            if isinstance(data, dict) and "tool" in data:
                return {"tool": data["tool"], "args": data.get("args", {})}
        except json.JSONDecodeError:
            pass

    # Strategy 3: JSON in fenced code blocks (clear intent)
    for pattern in [r'```json\s*(\{.*?\})\s*```', r'```\s*(\{.*?\})\s*```']:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                if isinstance(data, dict) and "tool" in data:
                    return {"tool": data["tool"], "args": data.get("args", {})}
            except json.JSONDecodeError:
                continue

    # Strategy 4: Positional analysis — detect if JSON is buried in narrative prose.
    #
    # Pattern: LLM outputs "I'll now run X...{"tool":...}...Once I get the output..."
    # The JSON sits in the MIDDLE of the text with substantial words both before
    # and after it.  That is a narrative hallucination — the LLM is describing a
    # hypothetical call, not issuing a real one.
    #
    # Acceptable patterns:
    #   - JSON only                          (Strategy 1 already handled)
    #   - Brief preamble then JSON at END    → still extract (common with some models)
    #   - TOOL_CALL: marker                  (Strategy 2 already handled)
    #   - Fenced code block                  (Strategy 3 already handled)
    #
    # Rejected pattern:
    #   - Significant text BEFORE the JSON AND significant text AFTER the JSON
    #
    tool_json_match = re.search(r'\{[\s\n]*["\']tool["\']\s*:', text)
    if tool_json_match:
        json_start = tool_json_match.start()
        extracted = _extract_balanced_json(text, json_start)
        if extracted:
            text_before = text[:json_start].strip()
            json_end = json_start + len(extracted)
            text_after = text[json_end:].strip()
            words_before = len(text_before.split()) if text_before else 0
            words_after = len(text_after.split()) if text_after else 0

            if words_before > 10 and words_after > 10:
                # JSON is embedded mid-prose — this is a narrative hallucination.
                # The LLM is describing what it would do, not actually doing it.
                return None

            # JSON at the end (preamble only) or at the start (trailing text only)
            # — still try to extract.
            try:
                data = json.loads(extracted)
                if isinstance(data, dict) and "tool" in data:
                    return {"tool": data["tool"], "args": data.get("args", {})}
            except json.JSONDecodeError:
                pass

    return None


def _extract_balanced_json(text: str, start: int) -> str | None:
    """Extract a balanced JSON object from text starting at 'start' position."""
    if start >= len(text) or text[start] != '{':
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None

    return None
