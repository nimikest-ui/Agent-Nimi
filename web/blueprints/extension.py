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
    """Build compact context block injected into extension chat prompts."""
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
        f"- form action={f.get('action','')} inputs={[i.get('name','') for i in f.get('inputs',[])]} "
        for f in forms[:5]
    )
    link_lines = "\n".join(f"- [{l.get('text','')}]({l.get('href','')})" for l in links[:15])

    return (
        "[PAGE CONTEXT]\n"
        f"Title: {title}\n"
        f"URL: {page_url}\n"
        f"MainText:\n{text}\n\n"
        f"Code Snippets:\n{snippet_lines or '- none'}\n\n"
        f"Forms:\n{form_lines or '- none'}\n\n"
        f"Links:\n{link_lines or '- none'}\n"
    )


def _coach_messages(user_msg: str, ctx_block: str) -> list[dict]:
    """Build extension chat prompt sequence."""
    system = (
        "You are AgentNimi — a sharp, capable AI sidekick with FULL BROWSER AWARENESS.\n"
        "You can see everything on the current page: its full text, code blocks, forms, links, and URL.\n"
        "You help with anything the user needs — research, coding, writing, debugging, hacking, shopping, whatever.\n"
        "\n"
        "CAPABILITIES YOU HAVE via the browser extension:\n"
        "- Read the full page content (text, snippets, forms, links)\n"
        "- Know the exact URL and page title\n"
        "- Observe form fields (names, types, current values)\n"
        "- See all code blocks rendered on the page\n"
        "- Instruct the user to click specific elements (by CSS selector)\n"
        "- Instruct the user to fill inputs or submit forms\n"
        "- Scroll to specific sections\n"
        "\n"
        "RULES:\n"
        "- Be concise and direct. No fluff, no disclaimers.\n"
        "- Reference specific page elements (forms, links, code) when relevant.\n"
        "- If the user asks you to do something on the page, give them the exact selector/step.\n"
        "- Help with whatever they need — no topic restrictions.\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": ctx_block + "\n[USER]\n" + user_msg},
    ]


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
        "captured_at": datetime.datetime.now().isoformat(),
    }
    state.set_extension_context(tab_key, context)
    audit_event(
        "extension_context_sync",
        {
            "tab_key": tab_key[:80],
            "url": str(context.get("url", ""))[:200],
            "text_len": len(str(context.get("text", ""))),
            "snippets": len(context.get("snippets", []) or []),
        },
    )
    resp = jsonify({"ok": True, "tab_key": tab_key})
    return _cors(resp)


@extension_bp.route("/chat", methods=["POST", "OPTIONS"])
def extension_chat():
    """Stream coach responses for extension side panel chats."""
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
    messages = _coach_messages(user_msg, _context_block(ext_ctx, max_chars=max_ctx))

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
            result = state.agent.provider.chat(messages, stream=True)
            chunks = []
            if isinstance(result, str):
                chunks.append(result)
                stream_callback(result)
            else:
                for chunk in result:
                    text = str(chunk)
                    chunks.append(text)
                    stream_callback(text)
            response = "".join(chunks)
            q.put({"type": "done", "content": response})
        except Exception as e:
            q.put({"type": "error", "message": str(e)})
        finally:
            q.put(None)

    thread = threading.Thread(target=run_agent, daemon=True)
    thread.start()

    def generate():
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
