"""Chrome extension bridge routes."""
import datetime
import json
import queue
import re
import threading
import uuid
from urllib.parse import urlparse
from flask import Blueprint, jsonify, request, Response, stream_with_context

from core.audit import audit_event
from web.utils import state

extension_bp = Blueprint("extension", __name__, url_prefix="/api/extension")

_PAGE_REF_RE = re.compile(
    r"\b(this|that|current)\s+(site|page|website|domain|url)\b"
    r"|\bhere\b"
    r"|\bthe one (?:we are|we're) viewing\b"
    r"|\bthe (?:site|page|website) (?:we are|we're) viewing\b",
    re.IGNORECASE,
)
_CONCRETE_TARGET_RE = re.compile(
    r"https?://\S+|\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b|\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\b",
    re.IGNORECASE,
)
_TARGET_REQUEST_RE = re.compile(r"\b(target|domain|url|ip|host|site)\b", re.IGNORECASE)
_STREAM_WORD_RE = re.compile(r"\S+\s*|\s+")


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


def _contains_page_reference(text: str) -> bool:
    return bool(_PAGE_REF_RE.search(text or ""))


def _has_concrete_target(text: str) -> bool:
    return bool(_CONCRETE_TARGET_RE.search(text or ""))


def _target_from_context(ctx: dict) -> str:
    page_url = str((ctx or {}).get("url", "")).strip()
    if not page_url:
        return ""
    parsed = urlparse(page_url)
    if parsed.hostname:
        return parsed.hostname
    if parsed.netloc:
        return parsed.netloc
    if "://" in page_url:
        return page_url.split("://", 1)[1].split("/", 1)[0]
    return page_url.split("/", 1)[0]


def _rewrite_page_reference(user_msg: str, target: str) -> str:
    return _PAGE_REF_RE.sub(target, user_msg or "")


def _last_assistant_message(messages: list[dict]) -> str:
    for msg in reversed(messages or []):
        if str(msg.get("role", "")) == "assistant":
            return str(msg.get("content", ""))
    return ""


def _assistant_waiting_for_target(messages: list[dict]) -> bool:
    last_reply = _last_assistant_message(messages).strip()
    if not last_reply:
        return False
    asks_question = "?" in last_reply
    asks_target = bool(_TARGET_REQUEST_RE.search(last_reply))
    return asks_question and asks_target


def _resolve_target_reference(user_msg: str, resolved_target: str, awaiting_target_reply: bool):
    """
    Resolve deictic target references ("this site", "the one we're viewing")
    without relying on action keyword lists.
    """
    normalized = str(user_msg or "")
    notes = []

    has_page_reference = _contains_page_reference(normalized)
    has_explicit_target = _has_concrete_target(normalized)

    if has_page_reference and not resolved_target:
        return "", "", (
            "I could not resolve the active page target. "
            "Refresh the page once and try again, or provide an explicit URL/domain/IP."
        )

    if has_page_reference and resolved_target:
        normalized = _rewrite_page_reference(normalized, resolved_target)
        notes.append(
            "[EXTENSION TARGET RESOLUTION]\n"
            f"Resolved page reference to active tab target: {resolved_target}\n"
            "Do not use placeholder phrases as tool targets.\n"
        )
    elif awaiting_target_reply and not has_explicit_target and resolved_target:
        # Follow-up answers like "the one we are viewing" / "that one" should map
        # to the active tab target when the previous assistant asked for a target.
        normalized = (
            f"{normalized}\n\n"
            f"[Resolved follow-up target from active browser tab: {resolved_target}]"
        )

    return normalized, "".join(notes), ""


def _iter_stream_units(text: str):
    """Yield text in small word-like units for smooth streaming in side panel."""
    raw = str(text or "")
    if not raw:
        return
    for unit in _STREAM_WORD_RE.findall(raw):
        if unit:
            yield unit


def _enqueue_stream_event(q, event_data):
    """Queue extension stream events, splitting text chunks word-by-word."""
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
    requested_conv_id = str(data.get("conversation_id") or "").strip()
    ext_ctx = state.get_extension_context(tab_key)
    resolved_target = _target_from_context(ext_ctx)

    # ── Resolve and/or reuse conversation for this tab ────────────────────────
    from web.services import conversation_service
    from config import SYSTEM_PROMPT
    from core.session_memory import start_engagement, add_finding

    conv_id = requested_conv_id or state.get_extension_conversation(tab_key) or str(uuid.uuid4())
    existing_conv = conversation_service.load_conversation(conv_id)
    awaiting_target_reply = _assistant_waiting_for_target(
        (existing_conv or {}).get("messages", [])
    )

    ext_conf = (state.config or {}).get("extension", {})
    max_ctx = int(ext_conf.get("max_context_chars", 8000) or 8000)

    normalized_user_msg, disambiguation_note, resolution_error = _resolve_target_reference(
        user_msg=user_msg,
        resolved_target=resolved_target,
        awaiting_target_reply=awaiting_target_reply,
    )
    if resolution_error:
        return _cors(jsonify({"error": resolution_error})), 400

    # Prepend page context so the agent knows what page the user is on.
    ctx_block = _context_block(ext_ctx, max_chars=max_ctx) if ext_ctx else ""
    prompt_parts = [
        ctx_block,
        (
            "[EXTENSION GUARDRAIL]\n"
            "Use ACTIVE_PAGE_URL/ACTIVE_PAGE_DOMAIN for page-referenced requests.\n"
            "Do not pass placeholders like 'this site' or 'this target' to tools.\n"
        ) if ctx_block else "",
        disambiguation_note,
        normalized_user_msg,
    ]
    full_msg = "\n".join(part for part in prompt_parts if part).strip()

    # ── Create a real conversation visible in the main web UI ──────────────────
    page_title = ext_ctx.get("title", "") if ext_ctx else ""
    if existing_conv:
        conv_data = existing_conv
        conv_data["source"] = conv_data.get("source", "extension")
    else:
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

    state.set_extension_conversation(tab_key, conv_id)

    # Rebuild agent context from the selected conversation.
    agent = state.get_agent(conv_id)
    agent.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in conv_data.get("messages", []):
        role = str(msg.get("role", "")).strip()
        content = str(msg.get("content", ""))
        if role in {"user", "assistant"} and content:
            agent.messages.append({"role": role, "content": content})
    state.set_current_conv_id(conv_id)
    start_engagement(conv_id, conv_data.get("title", ""))

    # Persist the user message (store the clean version, not the context-prefixed one)
    conv_data["messages"].append({
        "role": "user",
        "content": user_msg,
        "timestamp": datetime.datetime.now().isoformat(),
    })
    conversation_service.save_conversation(conv_id, conv_data)

    q = state.get_session(session_id)
    # Collect events for history replay (same as main chat)
    _ext_event_log: list[dict] = []
    _EXT_PERSIST_TYPES = frozenset({
        'task_classified', 'agent_start', 'mode_switched', 'routed',
        'multiagent_start', 'subtask_routed', 'subtask_done',
        'boss_routed', 'boss_approved', 'iteration', 'llm_call_done',
        'safety_check', 'tool_start', 'tool_result', 'learning',
        'agent_done', 'tool_blocked', 'stream_notice', 'mission_iteration',
    })

    def stream_callback(event_data):
        if isinstance(event_data, dict):
            normalized = dict(event_data)
            if 'event' in normalized and 'type' not in normalized:
                normalized['type'] = normalized['event']
            ev_type = str(normalized.get('type') or '')
            if ev_type in _EXT_PERSIST_TYPES:
                _ext_event_log.append(normalized)
        _enqueue_stream_event(q, event_data)

    def run_agent():
        try:
            # Full agent loop — nmap, shell, subdomains, all tools available
            response = agent.chat(full_msg, stream_callback=stream_callback)

            # Persist assistant response BEFORE sending done so the web UI
            # always sees the full conversation when it loads via the extension link.
            conv_data["messages"].append({
                "role": "assistant",
                "content": response,
                "events": _ext_event_log,
                "timestamp": datetime.datetime.now().isoformat(),
            })
            conversation_service.save_conversation(conv_id, conv_data)
            add_finding(conv_id, response[:3000])
            audit_event("extension_chat_complete", {"conversation_id": conv_id})
            q.put({"type": "done", "content": response, "conversation_id": conv_id})
        except Exception as e:
            q.put({"type": "error", "message": str(e)})
        finally:
            q.put(None)

    thread = threading.Thread(target=run_agent, daemon=True)
    thread.start()
    state.set_conv_thread(conv_id, thread, session_id)

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
