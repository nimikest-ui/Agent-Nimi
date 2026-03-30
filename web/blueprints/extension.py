"""Chrome extension bridge routes."""
import datetime
import json
import queue
import threading
import uuid
from flask import Blueprint, jsonify, request, Response, stream_with_context

from core.audit import audit_event
from web.utils import state

extension_bp = Blueprint("extension", __name__, url_prefix="/api/extension")


def _cors(resp):
    """Set permissive CORS headers for extension bridge endpoints."""
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return resp


def _context_block(ctx: dict, max_chars: int = 8000) -> str:
    """Build compact context block injected into the agent's user message."""
    title = str(ctx.get("title", "")).strip()
    page_url = str(ctx.get("url", "")).strip()
    main_text = str(ctx.get("text", "")).strip()
    snippets = ctx.get("snippets") or []
    if not isinstance(snippets, list):
        snippets = []
    snippets = [str(s).strip() for s in snippets if str(s).strip()]
    forms = ctx.get("forms") or []
    links = ctx.get("links") or []

    text = main_text[:max_chars]
    snippet_lines = "\n".join(f"- {s[:300]}" for s in snippets[:8])
    form_lines = "\n".join(
        f"- form action={f.get('action', '')} "
        f"inputs={[i.get('name', '') for i in f.get('inputs', [])]}"
        for f in forms[:5]
    )
    link_lines = "\n".join(
        f"- [{l.get('text', '')}]({l.get('href', '')})" for l in links[:15]
    )
    return (
        "[PAGE CONTEXT]\n"
        f"ACTIVE_PAGE_URL: {page_url}\n"
        f"ACTIVE_PAGE_DOMAIN: {page_url.split('/')[2] if '//' in page_url else page_url}\n"
        f"Title: {title}\n"
        f"NOTE: When the user says 'this site', 'this page', or 'here', they mean ACTIVE_PAGE_DOMAIN above.\n\n"
        f"MainText:\n{text}\n\n"
        f"Code Snippets:\n{snippet_lines or '- none'}\n\n"
        f"Forms:\n{form_lines or '- none'}\n\n"
        f"Links:\n{link_lines or '- none'}\n"
    )


@extension_bp.route("/health", methods=["GET", "OPTIONS"])
def extension_health():
    """Health endpoint for Chrome extension connectivity checks."""
    if request.method == "OPTIONS":
        return _cors(Response(status=204))
    provider = state.agent.provider.name() if state.agent else "uninitialized"
    resp = jsonify({"ok": True, "provider": provider})
    return _cors(resp)


@extension_bp.route("/context", methods=["POST", "OPTIONS"])
def extension_context():
    """Receive auto-synced page context from extension content script."""
    if request.method == "OPTIONS":
        return _cors(Response(status=204))
    payload = request.get_json() or {}
    tab_key = str(payload.get("tab_key") or payload.get("session_id") or "default")
    context = {
        "title": payload.get("title", ""),
        "url": payload.get("url", ""),
        "text": payload.get("text", ""),
        "snippets": payload.get("snippets", []),
        "forms": payload.get("forms", []),
        "links": payload.get("links", []),
        "captured_at": datetime.datetime.now().isoformat(),
    }
    state.set_extension_context(tab_key, context)
    audit_event(
        "extension_context_sync",
        {
            "tab_key": tab_key[:80],
            "url": str(context.get("url", ""))[:200],
            "text_len": len(str(context.get("text", ""))),
            "snippets": len(context.get("snippets") or []),
        },
    )
    resp = jsonify({"ok": True, "tab_key": tab_key})
    return _cors(resp)


@extension_bp.route("/chat", methods=["POST", "OPTIONS"])
def extension_chat():
    """Run extension chats through the real AgentNimi agent loop (tools included).

    Creates a real conversation in the main web UI and streams all agent events
    (tool calls, results, reasoning traces) back to the extension side panel.
    """
    if request.method == "OPTIONS":
        return _cors(Response(status=204))
    if not state.agent:
        return _cors(jsonify({"error": "Agent not initialized"})), 500

    data = request.get_json() or {}
    user_msg = str(data.get("message", "")).strip()
    if not user_msg:
        return _cors(jsonify({"error": "message required"})), 400

    tab_key = str(data.get("tab_key") or data.get("session_id") or "default")
    session_id = str(data.get("session_id") or uuid.uuid4())
    ext_ctx = state.get_extension_context(tab_key)

    ext_conf = (state.config or {}).get("extension", {})
    max_ctx = int(ext_conf.get("max_context_chars", 8000) or 8000)

    # Prepend page context so the agent knows what page the user is on
    ctx_block = _context_block(ext_ctx, max_chars=max_ctx) if ext_ctx else ""
    full_msg = (ctx_block + "\n" + user_msg).strip() if ctx_block else user_msg

    # ── Create a real conversation visible in the main web UI ──────────────────
    from web.services import conversation_service
    from config import SYSTEM_PROMPT
    from core.session_memory import start_engagement, add_finding

    conv_id = str(uuid.uuid4())
    page_title = ext_ctx.get("title", "") if ext_ctx else ""
    raw_title = f"[Browser] {page_title}: {user_msg}" if page_title else f"[Browser] {user_msg}"
    conv_title = conversation_service.generate_title(raw_title)
    conv_data = {
        "id": conv_id,
        "title": conv_title,
        "created_at": datetime.datetime.now().isoformat(),
        "updated_at": datetime.datetime.now().isoformat(),
        "messages": [],
        "source": "extension",
    }
    conversation_service.save_conversation(conv_id, conv_data)

    # Reset agent to a fresh conversation context
    state.agent.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    state.set_current_conv_id(conv_id)
    start_engagement(conv_id, conv_title)

    # Persist the user message (store the clean version, not the context-prefixed one)
    conv_data["messages"].append({
        "role": "user",
        "content": user_msg,
        "timestamp": datetime.datetime.now().isoformat(),
    })
    conversation_service.save_conversation(conv_id, conv_data)

    q = state.get_session(session_id)

    def stream_callback(event_data):
        if isinstance(event_data, dict):
            if "event" in event_data and "type" not in event_data:
                event_data = {**event_data, "type": event_data["event"]}
            q.put(event_data)
        else:
            q.put({"type": "chunk", "content": str(event_data)})

    def run_agent():
        try:
            # Full agent loop — nmap, shell, subdomains, all tools available
            response = state.agent.chat(full_msg, stream_callback=stream_callback)

            q.put({"type": "done", "content": response, "conversation_id": conv_id})

            # Persist assistant response
            conv_data["messages"].append({
                "role": "assistant",
                "content": response,
                "timestamp": datetime.datetime.now().isoformat(),
            })
            conversation_service.save_conversation(conv_id, conv_data)
            add_finding(conv_id, response[:3000])
            audit_event("extension_chat_complete", {"conversation_id": conv_id})
        except Exception as e:
            q.put({"type": "error", "message": str(e)})
        finally:
            q.put(None)

    thread = threading.Thread(target=run_agent, daemon=True)
    thread.start()

    def generate():
        # Immediately emit conversation_id so the side panel can show a link
        yield f"data: {json.dumps({'type': 'conversation_id', 'conversation_id': conv_id})}\n\n"
        waited = 0
        deadline = 600
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
        state.clear_session(session_id)

    resp = Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
    return _cors(resp)
