"""
Browser blueprint — HTTP API for the live browser panel in the chat UI.

Works with the thread-safe session model in tools/browser_tools.py:
  - All Playwright calls go through _submit() to the session's worker thread
  - latest_frame / frame_event can be read directly (Python value assignment is GIL-atomic)

Endpoints:
  POST /api/browser/open          { url } → { session_id, success }
  GET  /api/browser/<id>/stream   SSE stream of base64 PNG frames + URL info
  GET  /api/browser/<id>/status   { url, title, active }
  POST /api/browser/<id>/navigate { url } → { success }
  POST /api/browser/<id>/action   { type, ... } → { success }
  POST /api/browser/<id>/close    → { success }
  GET  /api/browser/sessions      → { sessions: [...] }
"""
from __future__ import annotations

import base64
import json
import threading

from flask import Blueprint, Response, request, jsonify, stream_with_context

browser_bp = Blueprint("browser", __name__)


def _tools():
    """Lazy import to avoid circular deps and handle missing playwright gracefully."""
    try:
        import tools.browser_tools as bt
        return bt
    except Exception:
        return None


# ── Open ──────────────────────────────────────────────────────────────────────

@browser_bp.route("/api/browser/open", methods=["POST"])
def browser_open():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "https://www.google.com").strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    bt = _tools()
    if bt is None:
        return jsonify({"success": False, "error": "Playwright not available"}), 500

    try:
        sid = bt._launch_session(url)
        return jsonify({"success": True, "session_id": sid, "url": url})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── SSE screenshot stream ─────────────────────────────────────────────────────

@browser_bp.route("/api/browser/<session_id>/stream")
def browser_stream(session_id: str):
    bt = _tools()
    if bt is None:
        return jsonify({"error": "Playwright not available"}), 500

    def generate():
        last_frame = None
        while True:
            with bt._sessions_lock:
                s = bt._sessions.get(session_id)
            if s is None:
                yield "event: closed\ndata: {}\n\n"
                break

            frame_bytes = s.get("latest_frame")
            if frame_bytes is not None and frame_bytes is not last_frame:
                last_frame = frame_bytes
                b64 = base64.b64encode(frame_bytes).decode()
                # Get URL non-blockingly — submit to worker
                try:
                    cur_url = bt._submit(s, lambda p: p.url, timeout=1.0)
                    title = bt._submit(s, lambda p: p.title(), timeout=1.0)
                except Exception:
                    cur_url = ""
                    title = ""
                payload = json.dumps({"frame": b64, "url": cur_url, "title": title})
                yield f"data: {payload}\n\n"
            else:
                yield ": keepalive\n\n"

            # Wait up to 300 ms for a new frame
            s["frame_event"].wait(timeout=0.3)
            s["frame_event"].clear()

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Status ────────────────────────────────────────────────────────────────────

@browser_bp.route("/api/browser/<session_id>/status")
def browser_status(session_id: str):
    bt = _tools()
    if bt is None:
        return jsonify({"active": False})
    with bt._sessions_lock:
        s = bt._sessions.get(session_id)
    if s is None or not s.get("stream_active", False):
        return jsonify({"active": False})
    try:
        url = bt._submit(s, lambda p: p.url, timeout=3.0)
        title = bt._submit(s, lambda p: p.title(), timeout=3.0)
        return jsonify({"active": True, "url": url, "title": title})
    except Exception as e:
        return jsonify({"active": False, "error": str(e)})


# ── Navigate ──────────────────────────────────────────────────────────────────

@browser_bp.route("/api/browser/<session_id>/navigate", methods=["POST"])
def browser_navigate(session_id: str):
    bt = _tools()
    if bt is None:
        return jsonify({"success": False, "error": "Playwright not available"}), 500
    with bt._sessions_lock:
        s = bt._sessions.get(session_id)
    if s is None:
        return jsonify({"success": False, "error": "Session not found"}), 404
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"success": False, "error": "url required"}), 400
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    # Dispatch navigate asynchronously so we don't block the HTTP response
    try:
        bt._submit(s, lambda p, u: p.goto(u, wait_until="domcontentloaded", timeout=30000), url, timeout=35.0)
        return jsonify({"success": True, "url": url})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── Action (click / type / key / scroll) ─────────────────────────────────────

@browser_bp.route("/api/browser/<session_id>/action", methods=["POST"])
def browser_action(session_id: str):
    bt = _tools()
    if bt is None:
        return jsonify({"success": False, "error": "Playwright not available"}), 500
    with bt._sessions_lock:
        s = bt._sessions.get(session_id)
    if s is None:
        return jsonify({"success": False, "error": "Session not found"}), 404

    data = request.get_json(silent=True) or {}
    action_type = data.get("type", "")

    def _act(page):
        if action_type == "click":
            page.mouse.click(float(data.get("x", 0)), float(data.get("y", 0)),
                             button=data.get("button", "left"))
        elif action_type == "dblclick":
            page.mouse.dblclick(float(data.get("x", 0)), float(data.get("y", 0)))
        elif action_type == "mousemove":
            page.mouse.move(float(data.get("x", 0)), float(data.get("y", 0)))
        elif action_type == "mousedown":
            page.mouse.move(float(data.get("x", 0)), float(data.get("y", 0)))
            page.mouse.down()
        elif action_type == "mouseup":
            page.mouse.up()
        elif action_type == "key":
            page.keyboard.press(data.get("key", ""))
        elif action_type == "type":
            page.keyboard.type(data.get("text", ""), delay=20)
        elif action_type == "scroll":
            page.mouse.wheel(float(data.get("deltaX", 0)), float(data.get("deltaY", 0)))
        else:
            raise ValueError(f"Unknown action type: {action_type}")

    try:
        bt._submit(s, _act, timeout=5.0)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── Close ─────────────────────────────────────────────────────────────────────

@browser_bp.route("/api/browser/<session_id>/close", methods=["POST"])
def browser_close(session_id: str):
    bt = _tools()
    if bt is None:
        return jsonify({"success": True})
    with bt._sessions_lock:
        s = bt._sessions.get(session_id)
    if s is None:
        return jsonify({"success": True, "note": "already closed"})
    # Send shutdown sentinel; the worker thread will clean up
    s["stream_active"] = False
    s["_queue"].put(None)
    return jsonify({"success": True})


# ── List sessions ─────────────────────────────────────────────────────────────

@browser_bp.route("/api/browser/sessions")
def browser_sessions():
    bt = _tools()
    if bt is None:
        return jsonify({"sessions": []})
    result = []
    with bt._sessions_lock:
        sids = list(bt._sessions.keys())
    for sid in sids:
        with bt._sessions_lock:
            s = bt._sessions.get(sid)
        if s is None:
            continue
        try:
            url = bt._submit(s, lambda p: p.url, timeout=1.0)
            title = bt._submit(s, lambda p: p.title(), timeout=1.0)
        except Exception:
            url = ""
            title = ""
        result.append({"session_id": sid, "url": url, "title": title})
    return jsonify({"sessions": result})
