"""
AgentNimi Web Server - Flask backend with SSE streaming
"""
import sys
import os
import json
import uuid
import queue
import threading
import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from config import load_config, save_config
from core.agent import AgentNimi
from core.monitor import SystemMonitor
from providers import list_providers
from tools.registry import _TOOLS
from tools.custom_loader import create_custom_tool, delete_custom_tool, list_custom_tools, refresh_agent_prompt

app = Flask(__name__, template_folder="templates", static_folder="static")

# Global state
config = load_config()
agent: AgentNimi = None
monitor: SystemMonitor = None
_sessions: dict[str, queue.Queue] = {}

# ──────────── Conversation Storage ────────────

CONV_DIR = Path.home() / ".agent-nimi" / "conversations"
CONV_DIR.mkdir(parents=True, exist_ok=True)

# Currently active conversation id
_current_conv_id: str = None


def _conv_path(conv_id: str) -> Path:
    return CONV_DIR / f"{conv_id}.json"


def _save_conversation(conv_id: str, data: dict):
    data["updated_at"] = datetime.datetime.now().isoformat()
    with open(_conv_path(conv_id), "w") as f:
        json.dump(data, f, indent=2)


def _load_conversation(conv_id: str) -> dict | None:
    p = _conv_path(conv_id)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return None


def _list_conversations() -> list[dict]:
    convs = []
    for p in CONV_DIR.glob("*.json"):
        try:
            with open(p) as f:
                data = json.load(f)
            convs.append({
                "id": data.get("id", p.stem),
                "title": data.get("title", "Untitled"),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "message_count": len(data.get("messages", [])),
            })
        except Exception:
            pass
    convs.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
    return convs


def _generate_title(message: str) -> str:
    """Generate a short title from the first user message."""
    title = message.strip().replace("\n", " ")
    if len(title) > 50:
        title = title[:47] + "..."
    return title


def init_agent(provider_name: str = None):
    """Initialize or reinitialize the agent."""
    global agent, monitor, config
    config = load_config()
    pname = provider_name or config.get("default_provider", "ollama")
    agent = AgentNimi(pname, config)
    if pname == "copilot":
        normalized = getattr(agent.provider, "model", "")
        if normalized and config["providers"].setdefault("copilot", {}).get("model") != normalized:
            config["providers"]["copilot"]["model"] = normalized
            save_config(config)
    if monitor is None:
        monitor = SystemMonitor(config)


# ──────────── Pages ────────────

@app.route("/")
def index():
    return render_template("index.html")


# ──────────── API ────────────

@app.route("/api/chat", methods=["POST"])
def chat():
    """Send a message and get a streaming response via SSE."""
    global _current_conv_id
    data = request.get_json()
    user_msg = data.get("message", "").strip()
    mode = data.get("mode", "agent")  # ask | agent | plan
    if not user_msg:
        return jsonify({"error": "Empty message"}), 400

    session_id = data.get("session_id", str(uuid.uuid4()))
    conv_id = data.get("conversation_id")

    # ── Create or load conversation ───────────────────────────────────────────
    if not conv_id:
        # Brand new conversation
        conv_id = str(uuid.uuid4())
        conv_data = {
            "id": conv_id,
            "title": _generate_title(user_msg),
            "created_at": datetime.datetime.now().isoformat(),
            "updated_at": datetime.datetime.now().isoformat(),
            "messages": [],
        }
        _save_conversation(conv_id, conv_data)
        conv = conv_data
    else:
        conv = _load_conversation(conv_id) or {
            "id": conv_id,
            "title": "Untitled",
            "messages": [],
            "created_at": datetime.datetime.now().isoformat(),
        }

    # ── Sync agent in-memory context if conversation changed ─────────────────
    # This is the key part: rebuild agent.messages from stored history so the
    # agent remembers everything from this conversation, regardless of which
    # conversation was active before.
    if conv_id != _current_conv_id or True:  # always sync to be safe
        from config import SYSTEM_PROMPT
        agent.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in conv.get("messages", []):
            agent.messages.append({"role": msg["role"], "content": msg["content"]})

    _current_conv_id = conv_id

    # ── Apply provider / model / key from request if specified ───────────────
    req_provider = data.get("provider", "").strip()
    req_model = data.get("model", "").strip()
    req_key = data.get("api_key", "").strip()
    if req_provider and req_provider != "ollama":
        if req_key:
            config["providers"].setdefault(req_provider, {})["api_key"] = req_key
        if req_model:
            config["providers"].setdefault(req_provider, {})["model"] = req_model
    if req_provider and req_provider != config.get("default_provider", "ollama"):
        try:
            agent.switch_provider(req_provider)
            config["default_provider"] = req_provider
        except Exception as _e:
            pass
    elif req_model and req_model != config["providers"].get(req_provider or config.get("default_provider", ""), {}).get("model", ""):
        pname = req_provider or config.get("default_provider", "ollama")
        config["providers"].setdefault(pname, {})["model"] = req_model
        try:
            agent.switch_provider(pname)
        except Exception:
            pass

    # ── Persist user message ──────────────────────────────────────────────────
    conv["messages"].append({
        "role": "user",
        "content": user_msg,
        "timestamp": datetime.datetime.now().isoformat(),
    })
    _save_conversation(conv_id, conv)

    # ── Stream the agent response ─────────────────────────────────────────────
    q = queue.Queue()
    _sessions[session_id] = q

    def stream_callback(event_data):
        if isinstance(event_data, dict):
            q.put(event_data)
        else:
            q.put({"type": "chunk", "content": event_data})

    def run_agent():
        try:
            if mode == "ask":
                # Direct LLM call — no agent loop, no tool calls
                msgs = list(agent.messages) + [{"role": "user", "content": user_msg}]
                full = ""
                result = agent.provider.chat(msgs, stream=True)
                if hasattr(result, "__iter__") and not isinstance(result, str):
                    for chunk in result:
                        q.put({"type": "chunk", "content": chunk})
                        full += chunk
                else:
                    full = str(result)
                    q.put({"type": "chunk", "content": full})
                response = full
            elif mode == "plan":
                # Agent loop with a planning prompt prefix
                plan_prefix = (
                    "Create a detailed, numbered step-by-step plan for the following task. "
                    "For each step specify what tools, commands, or techniques to use:\n\n"
                )
                response = agent.chat(plan_prefix + user_msg, stream_callback=stream_callback)
            else:
                # Default: full agent loop
                response = agent.chat(user_msg, stream_callback=stream_callback)
            q.put({"type": "done", "content": response, "conversation_id": conv_id})
            # Persist assistant response
            saved_conv = _load_conversation(conv_id)
            if saved_conv:
                saved_conv["messages"].append({
                    "role": "assistant",
                    "content": response,
                    "timestamp": datetime.datetime.now().isoformat(),
                })
                _save_conversation(conv_id, saved_conv)
        except Exception as e:
            q.put({"type": "error", "content": str(e)})
        finally:
            q.put(None)  # Sentinel

    thread = threading.Thread(target=run_agent, daemon=True)
    thread.start()

    def generate():
        while True:
            try:
                item = q.get(timeout=300)
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'error', 'content': 'Timeout'})}\n\n"
                break
        _sessions.pop(session_id, None)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/cancel", methods=["POST"])
def cancel():
    """Cancel the currently running agent operation."""
    if agent:
        agent.cancel()
    # Also drain any active session queues so the SSE stream ends
    data = request.get_json() or {}
    sid = data.get("session_id")
    if sid and sid in _sessions:
        _sessions[sid].put(None)  # Sentinel to end the SSE stream
    return jsonify({"success": True})


# ──────────── Conversation History API ────────────

@app.route("/api/conversations")
def list_convs():
    """List all saved conversations."""
    return jsonify({"conversations": _list_conversations()})


@app.route("/api/conversations/<conv_id>")
def get_conv(conv_id):
    """Get a specific conversation."""
    conv = _load_conversation(conv_id)
    if not conv:
        return jsonify({"error": "Not found"}), 404
    return jsonify(conv)


@app.route("/api/conversations", methods=["POST"])
def create_conv():
    """Create a new conversation."""
    global _current_conv_id
    conv_id = str(uuid.uuid4())
    data = request.get_json() or {}
    conv = {
        "id": conv_id,
        "title": data.get("title", "New Chat"),
        "created_at": datetime.datetime.now().isoformat(),
        "updated_at": datetime.datetime.now().isoformat(),
        "messages": [],
    }
    _save_conversation(conv_id, conv)
    _current_conv_id = conv_id
    # Reset agent conversation
    if agent:
        agent.reset_conversation()
    return jsonify(conv)


@app.route("/api/conversations/<conv_id>", methods=["PUT"])
def update_conv(conv_id):
    """Update conversation title."""
    conv = _load_conversation(conv_id)
    if not conv:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json() or {}
    if "title" in data:
        conv["title"] = data["title"]
    _save_conversation(conv_id, conv)
    return jsonify({"success": True})


@app.route("/api/conversations/<conv_id>", methods=["DELETE"])
def delete_conv(conv_id):
    """Delete a conversation."""
    global _current_conv_id
    p = _conv_path(conv_id)
    if p.exists():
        p.unlink()
    if _current_conv_id == conv_id:
        _current_conv_id = None
        if agent:
            agent.reset_conversation()
    return jsonify({"success": True})


@app.route("/api/conversations/<conv_id>/load", methods=["POST"])
def load_conv(conv_id):
    """Load a conversation into the agent."""
    global _current_conv_id
    conv = _load_conversation(conv_id)
    if not conv:
        return jsonify({"error": "Not found"}), 404
    _current_conv_id = conv_id
    # Rebuild agent messages from conversation history
    if agent:
        from config import SYSTEM_PROMPT
        agent.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in conv.get("messages", []):
            agent.messages.append({"role": msg["role"], "content": msg["content"]})
    return jsonify({"success": True, "conversation": conv})


@app.route("/api/steer", methods=["POST"])
def steer():
    """Inject a steering message into the running agent loop."""
    data = request.get_json() or {}
    msg = data.get("message", "").strip()
    sid = data.get("session_id")
    if not msg:
        return jsonify({"error": "Empty message"}), 400
    if agent:
        agent.steer(msg)
    # Also push a steer echo into the SSE stream so front-end sees it
    if sid and sid in _sessions:
        _sessions[sid].put({"event": "steer_echo", "message": msg})
    return jsonify({"success": True})


@app.route("/api/status")
def status():
    """Get agent and system status."""
    connected = False
    provider_name = ""
    try:
        if agent:
            connected = agent.provider.test_connection()
            provider_name = agent.provider.name()
    except Exception:
        pass

    return jsonify({
        "provider": provider_name,
        "default_provider": config.get("default_provider", "ollama"),
        "current_model": config["providers"].get(config.get("default_provider", "ollama"), {}).get("model", ""),
        "connected": connected,
        "monitor_running": monitor.is_running if monitor else False,
        "alerts": monitor.get_alerts(10) if monitor else [],
        "history": agent.get_history_summary() if agent else "",
        "routing_active": agent.routing_active if agent else False,
        "router_enabled": bool(agent and agent.router and agent.router.enabled),
        "routed_to": agent.router.name() if (agent and agent.router) else "",
    })


@app.route("/api/providers")
def providers():
    """List available providers."""
    result = []
    for p in list_providers():
        pconf = config["providers"].get(p, {})
        result.append({
            "name": p,
            "model": pconf.get("model", ""),
            "has_key": bool(pconf.get("api_key")) or p == "ollama",
            "current": agent and p in agent.provider.name().lower(),
        })
    return jsonify(result)


@app.route("/api/provider", methods=["POST"])
def switch_provider():
    """Switch LLM provider."""
    data = request.get_json()
    name = data.get("name", "")
    try:
        agent.switch_provider(name)
        config["default_provider"] = name
        save_config(config)
        return jsonify({"success": True, "provider": agent.provider.name()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/model", methods=["POST"])
def set_model():
    """Change model for a provider and persist it immediately."""
    data = request.get_json()
    model = data.get("model", "").strip()
    pname = data.get("provider", config.get("default_provider", "ollama")).strip() or config.get("default_provider", "ollama")
    if not model:
        return jsonify({"success": False, "error": "Missing model"}), 400
    config.setdefault("providers", {}).setdefault(pname, {})["model"] = model
    save_config(config)
    if pname == config.get("default_provider", "ollama"):
        agent.switch_provider(pname)
    return jsonify({"success": True, "model": model, "provider": agent.provider.name()})


# Known models per provider
PROVIDER_MODELS = {
    "ollama": [],  # populated dynamically from local ollama
    "openrouter": [
        "meta-llama/llama-3-70b-instruct",
        "meta-llama/llama-3.1-405b-instruct",
        "meta-llama/llama-3.1-70b-instruct",
        "meta-llama/llama-3.1-8b-instruct",
        "mistralai/mistral-large",
        "mistralai/mixtral-8x22b-instruct",
        "mistralai/mistral-small",
        "google/gemini-pro-1.5",
        "google/gemini-2.0-flash-001",
        "anthropic/claude-3.5-sonnet",
        "anthropic/claude-3-opus",
        "anthropic/claude-3-haiku",
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
        "openai/gpt-4-turbo",
        "deepseek/deepseek-chat",
        "deepseek/deepseek-r1",
        "qwen/qwen-2.5-72b-instruct",
        "cohere/command-r-plus",
    ],
    "grok": [
        "grok-3",
        "grok-3-fast",
        "grok-3-mini",
        "grok-3-mini-fast",
        "grok-2",
        "grok-2-mini",
    ],
    "copilot": [
        "gpt-4.1",
        "gpt-4o",
        "gpt-5-mini",
        "claude-haiku-4.5",
        "claude-sonnet-4.5",
        "claude-sonnet-4.6",
        "gpt-5.2",
        "gpt-5.3-codex",
    ],
}


@app.route("/api/models")
def models():
    """Get available models for a provider."""
    provider_name = request.args.get("provider", config.get("default_provider", "ollama"))
    current_model = config["providers"].get(provider_name, {}).get("model", "")

    if provider_name == "ollama":
        # Fetch local models from Ollama
        try:
            import requests as req
            base_url = config["providers"]["ollama"].get("base_url", "http://localhost:11434")
            resp = req.get(f"{base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            model_list = [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            model_list = ["llama3", "llama3:70b", "mistral", "codellama", "phi3", "gemma2", "qwen2.5"]
    elif provider_name == "copilot":
        model_list = PROVIDER_MODELS.get(provider_name, [])
    else:
        model_list = PROVIDER_MODELS.get(provider_name, [])

    return jsonify({
        "models": model_list,
        "current": current_model,
    })


@app.route("/api/setkey", methods=["POST"])
def set_api_key():
    """Set API key for current provider."""
    data = request.get_json()
    key = data.get("key", "")
    provider_name = data.get("provider", config.get("default_provider", "ollama"))
    config["providers"][provider_name]["api_key"] = key
    save_config(config)
    agent.switch_provider(provider_name)
    connected = agent.provider.test_connection()
    return jsonify({"success": True, "connected": connected})


@app.route("/api/clear", methods=["POST"])
def clear_history():
    """Clear the current conversation's messages (keeps the conversation shell)."""
    global _current_conv_id
    if agent:
        agent.reset_conversation()
    # Also wipe stored messages for the current conversation
    if _current_conv_id:
        conv = _load_conversation(_current_conv_id)
        if conv:
            conv["messages"] = []
            _save_conversation(_current_conv_id, conv)
    return jsonify({"success": True, "conversation_id": _current_conv_id})


@app.route("/api/tools")
def tools():
    """List available tools."""
    result = []
    for name, info in _TOOLS.items():
        result.append({
            "name": name,
            "description": info["description"],
            "custom": info.get("custom", False),
        })
    return jsonify(result)


@app.route("/api/tools/custom")
def custom_tools():
    """List custom tools with full metadata."""
    return jsonify(list_custom_tools())


@app.route("/api/tools/generate", methods=["POST"])
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
        response = agent.provider.chat(
            [{"role": "user", "content": prompt}],
            stream=False
        )
        # Strip markdown code fences if present
        text = str(response).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0].strip()
        import re as _re
        # Extract first JSON object
        m = _re.search(r'\{[\s\S]+\}', text)
        if not m:
            return jsonify({"success": False, "message": "LLM did not return JSON", "raw": text}), 500
        spec = json.loads(m.group())
        return jsonify({"success": True, "spec": spec})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/tools/create", methods=["POST"])
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
    if result["success"] and agent:
        refresh_agent_prompt(agent)

    return jsonify(result), 200 if result["success"] else 400


@app.route("/api/tools/delete", methods=["POST"])
def delete_tool():
    """Delete a custom tool."""
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"success": False, "message": "Name is required."}), 400

    result = delete_custom_tool(name)

    if result["success"] and agent:
        refresh_agent_prompt(agent)

    return jsonify(result), 200 if result["success"] else 400


def _refresh_agent_prompt():
    """Rebuild the system prompt (legacy wrapper)."""
    if agent:
        refresh_agent_prompt(agent)


@app.route("/api/router/stats")
def router_stats():
    """Return smart router learned scores and recent history."""
    if not agent:
        return jsonify({"error": "Agent not initialized"}), 503
    stats = agent.router_stats()
    if stats is None:
        return jsonify({"enabled": False, "message": "Smart routing disabled in config"})
    return jsonify(stats)


@app.route("/api/router/toggle", methods=["POST"])
def router_toggle():
    """Enable or disable smart routing."""
    if not agent:
        return jsonify({"success": False, "error": "Agent not initialized"}), 503
    data = request.get_json() or {}
    enable = data.get("enabled", True)
    if enable:
        agent.enable_routing()
    else:
        agent.disable_routing()
    return jsonify({
        "success": True,
        "routing_active": agent.routing_active,
        "router_enabled": bool(agent.router and agent.router.enabled),
    })


@app.route("/api/monitor/start", methods=["POST"])
def monitor_start():
    monitor.start()
    return jsonify({"success": True, "running": True})


@app.route("/api/monitor/stop", methods=["POST"])
def monitor_stop():
    monitor.stop()
    return jsonify({"success": True, "running": False})


@app.route("/api/monitor/stats")
def monitor_stats():
    """Return live system stats and recent alerts."""
    stats = monitor.get_stats()
    alerts = [f"[{a['type'].upper()}] {a['message']}" for a in monitor.get_alerts(10)]
    return jsonify({"system": stats, "alerts": alerts, "running": monitor.is_running})


# Keep legacy POST endpoint for backwards compat
@app.route("/api/monitor", methods=["POST"])
def monitor_control():
    data = request.get_json() or {}
    action = data.get("action", "")
    if action == "start":
        monitor.start()
        return jsonify({"success": True, "running": True})
    elif action == "stop":
        monitor.stop()
        return jsonify({"success": True, "running": False})
    return jsonify({"error": "Invalid action"}), 400


@app.route("/api/system")
def system_info():
    """Quick system info for the dashboard."""
    stats = monitor.get_stats()
    return jsonify(stats)



@app.route("/api/shutdown", methods=["POST"])
def shutdown_server():
    """Shut down the web server process."""
    import signal
    threading.Timer(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    return jsonify({"ok": True})


@app.route("/api/restart", methods=["POST"])
def restart_server():
    """Restart the web server by re-execing the current process."""
    def _do_restart():
        import time
        time.sleep(0.6)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    threading.Thread(target=_do_restart, daemon=True).start()
    return jsonify({"ok": True})


def run_web(host: str = "0.0.0.0", port: int = 1337, debug: bool = False):
    """Start the web server."""
    init_agent()
    print(f"\n  🌐 AgentNimi Web UI: http://{host}:{port}")
    print(f"  Provider: {agent.provider.name()}\n")
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    run_web(debug=True)
