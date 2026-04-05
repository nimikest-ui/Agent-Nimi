"""Chat and streaming routes."""
import json
import re
import uuid
import queue
import threading
import datetime
from flask import Blueprint, jsonify, request, Response, stream_with_context
from config import SYSTEM_PROMPT, add_copilot_usage, save_config
from core.evaluator import get_copilot_multiplier
from core.session_memory import start_engagement, add_in_flight, add_finding, clear_engagement
from core.audit import audit_event
from web.services import conversation_service
from web.utils import state

chat_bp = Blueprint('chat', __name__, url_prefix='/api')
_STREAM_WORD_RE = re.compile(r"\S+\s*|\s+")


def _iter_stream_units(text: str):
    """Yield text in small word-like units for smoother live rendering."""
    raw = str(text or "")
    if not raw:
        return
    for unit in _STREAM_WORD_RE.findall(raw):
        if unit:
            yield unit


def _enqueue_stream_event(q, event_data):
    """Queue stream events, splitting text chunks into word-level pieces."""
    if isinstance(event_data, dict):
        if "event" in event_data and "type" not in event_data:
            event_data = {**event_data, "type": event_data["event"]}

        ev_type = str(event_data.get("type") or "")
        if ev_type in {"chunk", "text_chunk"}:
            original_text = event_data.get("content")
            if original_text is None:
                original_text = event_data.get("text", "")
            for unit in _iter_stream_units(original_text):
                payload = dict(event_data)
                payload["content"] = unit
                if "text" in payload and payload.get("text") == original_text:
                    payload["text"] = unit
                q.put(payload)
            return

        q.put(event_data)
        return

    for unit in _iter_stream_units(event_data):
        q.put({"type": "chunk", "content": unit})


@chat_bp.route('/chat', methods=['POST'])
def chat():
    """Send a message and get a streaming response via SSE.

    Each conversation gets its own AgentNimi from the pool, so multiple
    chats can run truly in parallel without corrupting each other.
    """
    data = request.get_json()
    user_msg = data.get("message", "").strip()
    display_msg = data.get("display_message", "").strip() or user_msg
    mode = data.get("mode", "agent")  # ask | agent | plan
    if not user_msg:
        return jsonify({"error": "Empty message"}), 400

    session_id = data.get("session_id", str(uuid.uuid4()))
    conv_id = data.get("conversation_id")

    audit_event("chat_request", {"mode": mode, "conversation_id": conv_id or "", "session_id": session_id})

    # ── Create or load conversation ───────────────────────────────────────────
    if not conv_id:
        conv_id = str(uuid.uuid4())
        conv_data = {
            "id": conv_id,
            "title": conversation_service.generate_title(display_msg),
            "created_at": datetime.datetime.now().isoformat(),
            "updated_at": datetime.datetime.now().isoformat(),
            "messages": [],
        }
        conversation_service.save_conversation(conv_id, conv_data)
        conv = conv_data
    else:
        conv = conversation_service.load_conversation(conv_id) or {
            "id": conv_id,
            "title": "Untitled",
            "messages": [],
            "created_at": datetime.datetime.now().isoformat(),
        }

    # ── Get (or create) a per-conversation agent ─────────────────────────────
    # Cancel any previous run *on this same conversation* (e.g. user resends).
    prev_thread = state.get_conv_thread(conv_id)
    if prev_thread and prev_thread.is_alive():
        state.cancel_conv(conv_id, timeout=6.0)

    agent = state.get_agent(conv_id)
    agent.set_mode(mode)

    # Rebuild messages from stored history (only needed on fresh agent)
    if len(agent.messages) <= 1:
        agent.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in conv.get("messages", []):
            agent.messages.append({"role": msg["role"], "content": msg["content"]})

    state.set_current_conv_id(conv_id)
    start_engagement(conv_id, conv.get("title", ""))

    # ── Apply provider / model from request if specified ─────────────────────
    req_provider = data.get("provider", "").strip()
    req_model = data.get("model", "").strip()

    if req_provider:
        if req_model:
            state.config["providers"].setdefault(req_provider, {})["model"] = req_model
    if req_provider and req_provider != state.config.get("default_provider", "grok"):
        try:
            agent.switch_provider(req_provider)
            state.config["default_provider"] = req_provider
        except Exception:
            pass
    elif req_model:
        current_provider = req_provider or state.config.get("default_provider", "grok")
        current_model = state.config["providers"].get(current_provider, {}).get("model", "")
        if req_model != current_model:
            pname = req_provider or state.config.get("default_provider", "grok")
            state.config["providers"].setdefault(pname, {})["model"] = req_model
            try:
                agent.switch_provider(pname)
            except Exception:
                pass

    # ── Persist user message ──────────────────────────────────────────────────
    conv["messages"].append({
        "role": "user",
        "content": display_msg,
        "timestamp": datetime.datetime.now().isoformat(),
    })
    add_in_flight(conv_id, display_msg)
    conversation_service.save_conversation(conv_id, conv)

    # ── Stream the agent response ─────────────────────────────────────────────
    q = state.get_session(session_id)
    # Collect non-text events so they can be persisted for history replay
    _event_log: list[dict] = []
    _PERSIST_TYPES = frozenset({
        'task_classified', 'agent_start', 'mode_switched', 'routed',
        'multiagent_start', 'subtask_escalated', 'subtask_stuck',
        'subtask_routed', 'subtask_done', 'boss_routed', 'boss_approved',
        'boss_refinement', 'multiagent_replan', 'mission_iteration',
        'mission_adapting', 'multiagent_done', 'iteration',
        'llm_call_done', 'safety_check', 'tool_start', 'tool_result',
        'learning', 'agent_done', 'tool_blocked', 'reasoning_trace',
        'reflection', 'provider_degraded', 'reflexion_retry',
        'workflow_tool_blocked', 'tool_declined', 'confirm_request',
        'stream_notice',
    })

    def stream_callback(event_data):
        if isinstance(event_data, dict):
            normalized = dict(event_data)
            if 'event' in normalized and 'type' not in normalized:
                normalized['type'] = normalized['event']
            ev_type = str(normalized.get('type') or '')
            if ev_type in _PERSIST_TYPES:
                _event_log.append(normalized)
            if ev_type not in {'text_chunk', 'chunk'}:
                audit_event('stream_event', normalized)
        _enqueue_stream_event(q, event_data)

    def run_agent():
        try:
            if mode == "ask":
                msgs = list(agent.messages) + [{"role": "user", "content": user_msg}]
                full = ""
                result = agent.provider.chat(msgs, stream=True)
                if hasattr(result, "__iter__") and not isinstance(result, str):
                    for chunk in result:
                        _enqueue_stream_event(q, {"type": "chunk", "content": chunk})
                        full += chunk
                else:
                    _enqueue_stream_event(q, {"type": "stream_notice", "message": "provider returned non-streaming response"})
                    full = str(result)
                    _enqueue_stream_event(q, {"type": "chunk", "content": full})
                response = full
                active_provider = req_provider or state.config.get("default_provider", "grok")
                active_model = req_model or state.config.get("providers", {}).get(active_provider, {}).get("model", "")
                if active_provider == "copilot":
                    add_copilot_usage(state.config, get_copilot_multiplier(active_model))
                    save_config(state.config)
            elif mode == "plan":
                plan_prefix = (
                    "Create a detailed, numbered step-by-step plan for the following task. "
                    "For each step specify what tools, commands, or techniques to use:\n\n"
                )
                response = agent.chat(plan_prefix + user_msg, stream_callback=stream_callback)
            else:
                response = agent.chat(user_msg, stream_callback=stream_callback)

            conv["messages"].append({
                "role": "assistant",
                "content": response,
                "events": _event_log,
                "timestamp": datetime.datetime.now().isoformat(),
            })
            conversation_service.save_conversation(conv_id, conv)
            add_finding(conv_id, response[:3000])
            q.put({"type": "done", "content": response, "conversation_id": conv_id})
        except Exception as e:
            audit_event("chat_error", {"error": str(e)[:1200], "conversation_id": conv_id})
            q.put({"type": "error", "message": str(e)})
        finally:
            q.put(None)  # Sentinel

    thread = threading.Thread(target=run_agent, daemon=True)
    thread.start()
    state.set_conv_thread(conv_id, thread, session_id)

    def generate():
        yield f"data: {json.dumps({'type': 'conversation_id', 'conversation_id': conv_id})}\n\n"
        deadline = 600
        waited = 0
        while waited < deadline:
            try:
                item = q.get(timeout=15)
                if item is None:
                    break
                waited = 0
                yield f"data: {json.dumps(item)}\n\n"
            except queue.Empty:
                if not thread.is_alive():
                    break
                waited += 15
                yield ": keepalive\n\n"
        else:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Request timed out after 10 minutes'})}\n\n"
        state.clear_session(session_id)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@chat_bp.route('/cancel', methods=['POST'])
def cancel():
    """Cancel the currently running agent operation.

    Accepts an optional ``conversation_id`` to cancel a specific chat.
    Without it, cancels *all* running conversations (legacy behaviour).
    """
    data = request.get_json(silent=True) or {}
    conv_id = data.get("conversation_id")
    if conv_id:
        state.cancel_conv(conv_id, timeout=5.0)
    else:
        # Legacy: cancel everything
        if state.agent:
            state.agent.cancel()
        active = state.get_active_session()
        if active:
            state.poison_session(active)
        state.cancel_and_wait(timeout=5.0)
    return jsonify({"ok": True})


@chat_bp.route('/steer', methods=['POST'])
def steer():
    """Inject a steering message into the running agent loop."""
    data = request.get_json() or {}
    session_id = data.get("session_id")
    conv_id = data.get("conversation_id")
    message = data.get("message", "").strip()
    
    if not message:
        return jsonify({"error": "message required"}), 400

    # Resolve agent: prefer per-conversation, fall back to global
    agent = state.get_agent(conv_id) if conv_id else state.agent

    lowered = message.lower()
    if lowered in {"!ask", "!plan", "!agent"}:
        mode = lowered[1:]
        if agent:
            agent.request_mode_switch(mode)
        return jsonify({"ok": True, "mode_switch": mode})
    
    if agent:
        agent.steer(message)
    
    return jsonify({"ok": True})
