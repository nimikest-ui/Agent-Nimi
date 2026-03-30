"""Tools management routes."""
import json
import re as _re
from flask import Blueprint, jsonify, request
from tools.registry import _TOOLS, list_tool_manifests, discover_tools
from tools.custom_loader import (
    create_custom_tool,
    delete_custom_tool,
    list_custom_tools,
    refresh_agent_prompt
)
from web.utils import state

tools_bp = Blueprint('tools', __name__, url_prefix='/api/tools')


@tools_bp.route('')
def list_tools():
    """List available tools."""
    result = []
    for name, info in _TOOLS.items():
        result.append({
            "name": name,
            "description": info["description"],
            "custom": info.get("custom", False),
            "manifest": info.get("manifest", {}),
        })
    return jsonify(result)


@tools_bp.route('/manifests')
def list_manifests():
    """Return all tool manifests for discovery/routing."""
    return jsonify({"manifests": list_tool_manifests()})


@tools_bp.route('/discover')
def discover():
    """Discover tools by capability/trust/provider filters."""
    capability = (request.args.get("capability") or "").strip()
    trust_tier = (request.args.get("trust_tier") or "").strip()
    provider_affinity = (request.args.get("provider_affinity") or "").strip()
    return jsonify({
        "tools": discover_tools(
            capability=capability,
            trust_tier=trust_tier,
            provider_affinity=provider_affinity,
        )
    })


@tools_bp.route('/custom')
def get_custom_tools():
    """List custom tools with full metadata."""
    return jsonify(list_custom_tools())


@tools_bp.route('/generate', methods=['POST'])
def generate_tool():
    """Use the LLM to generate a full tool spec from a natural language description."""
    data = request.get_json() or {}
    description = data.get("description", "").strip()
    if not description:
        return jsonify({"success": False, "message": "Description required"}), 400

    prompt = f"""You are a tool-creation assistant. Given a description, output ONLY valid JSON (no markdown, no explanation) for a Python tool with this exact schema:
{{
  "name": "snake_case_name",
  "description": "one-line description",
  "args": [
    {{"name": "arg_name", "type": "str", "description": "what it is", "required": true}}
  ],
  "code": "python function body that uses the args as local variables and returns a string result"
}}

Rules for the code field:
- The args are already available as local variables — do NOT define a function, just write the body.
- Always return a string.
- Use only stdlib modules (subprocess, os, pathlib, json, re, datetime, requests if needed).
- Handle exceptions and return an error string if something fails.

Description: {description}"""

    try:
        if not state.agent:
            return jsonify({"success": False, "message": "No agent initialized"}), 500
            
        response = state.agent.provider.chat(
            [{"role": "user", "content": prompt}],
            stream=False
        )
        # Strip markdown code fences if present
        text = str(response).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0].strip()
        
        # Extract first JSON object
        m = _re.search(r'\{[\s\S]+\}', text)
        if not m:
            return jsonify({"success": False, "message": "LLM did not return JSON", "raw": text}), 500
        spec = json.loads(m.group())
        return jsonify({"success": True, "spec": spec})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@tools_bp.route('/create', methods=['POST'])
def create_tool():
    """Create a new custom tool."""
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    description = data.get("description", "").strip()
    args_schema = data.get("args", [])
    code = data.get("code", "").strip()

    if not name or not code:
        return jsonify({"success": False, "message": "Name and code are required."}), 400

    result = create_custom_tool(name, description, args_schema, code)

    # Update the agent system prompt to include the new tool
    if result["success"] and state.agent:
        refresh_agent_prompt(state.agent)

    return jsonify(result), 200 if result["success"] else 400


@tools_bp.route('/delete', methods=['POST'])
def delete_tool():
    """Delete a custom tool."""
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"success": False, "message": "Name is required."}), 400

    result = delete_custom_tool(name)

    if result["success"] and state.agent:
        refresh_agent_prompt(state.agent)

    return jsonify(result), 200 if result["success"] else 400
