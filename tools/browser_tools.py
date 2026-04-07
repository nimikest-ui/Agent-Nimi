"""
Browser tools — gives the agent full control of a Playwright browser instance.

THREADING MODEL: Playwright's sync API is NOT thread-safe — every Page/Browser
call must happen on the thread that called sync_playwright().start().

Each session owns a dedicated "playwright worker thread". All browser ops are
dispatched to that thread via a task queue + concurrent.futures.Future.

Sessions are stored in _sessions and shared with web/blueprints/browser.py.
"""
from __future__ import annotations

import base64
import queue
import threading
import uuid
from concurrent.futures import Future
from typing import Any, Callable

from tools.registry import tool

# ── Session store ─────────────────────────────────────────────────────────────
_sessions: dict[str, dict] = {}
_sessions_lock = threading.Lock()
_FPS = 4


# ── Worker thread ─────────────────────────────────────────────────────────────

def _playwright_worker(sid: str, session: dict, url: str) -> None:
    """Long-lived thread that owns ALL Playwright objects for one session."""
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        session["_error"] = str(e)
        session["_ready_evt"].set()
        return

    session["_ready_evt"].set()
    task_q: queue.Queue = session["_queue"]
    frame_interval = 1.0 / _FPS

    while session.get("stream_active", True):
        # Drain all pending tasks first
        while True:
            try:
                item = task_q.get_nowait()
            except queue.Empty:
                break
            if item is None:
                session["stream_active"] = False
                break
            fn, args, kwargs, fut = item
            try:
                fut.set_result(fn(page, *args, **kwargs))
            except Exception as exc:
                fut.set_exception(exc)

        if not session.get("stream_active", True):
            break

        # Capture screenshot
        try:
            png = page.screenshot(timeout=2000)
            session["latest_frame"] = png
            session["frame_event"].set()
        except Exception:
            pass

        # Wait for next task or frame tick
        try:
            item = task_q.get(timeout=frame_interval)
        except queue.Empty:
            continue

        if item is None:
            session["stream_active"] = False
            break
        fn, args, kwargs, fut = item
        try:
            fut.set_result(fn(page, *args, **kwargs))
        except Exception as exc:
            fut.set_exception(exc)

    # Cleanup
    try:
        browser.close()
        pw.stop()
    except Exception:
        pass
    with _sessions_lock:
        _sessions.pop(sid, None)


def _submit(session: dict, fn: Callable, *args, timeout: float = 10.0, **kwargs) -> Any:
    """Dispatch a callable to the session's playwright worker thread and wait for the result."""
    if not session.get("stream_active", True):
        raise RuntimeError("Browser session has been closed.")
    fut: Future = Future()
    session["_queue"].put((fn, args, kwargs, fut))
    return fut.result(timeout=timeout)


def _launch_session(url: str) -> str:
    """Create a new browser session on a dedicated worker thread. Returns session_id."""
    sid = uuid.uuid4().hex[:12]
    session: dict[str, Any] = {
        "_queue": queue.Queue(),
        "latest_frame": None,
        "frame_event": threading.Event(),
        "stream_active": True,
        "_ready_evt": threading.Event(),
        "_error": None,
    }
    with _sessions_lock:
        _sessions[sid] = session
    t = threading.Thread(target=_playwright_worker, args=(sid, session, url), daemon=True)
    t.start()
    # Block until browser is ready (up to 35 s)
    session["_ready_evt"].wait(timeout=35)
    if session["_error"]:
        with _sessions_lock:
            _sessions.pop(sid, None)
        raise RuntimeError(session["_error"])
    return sid


def _get_session(session_id: str) -> dict:
    with _sessions_lock:
        s = _sessions.get(session_id)
    if s is None:
        raise ValueError(f"No browser session '{session_id}'. Call browser_open first.")
    if not s.get("stream_active", True):
        raise ValueError(f"Browser session '{session_id}' is closed.")
    return s


# ── Agent-facing tools ────────────────────────────────────────────────────────

@tool(
    name="browser_open",
    description=(
        "Open a new Playwright browser and navigate to a URL. "
        "Returns a session_id that MUST be passed to all other browser_* tools. "
        "The live browser panel in the chat UI will display this session."
    ),
    manifest={
        "category": "browser",
        "action_class": "reversible",
        "capabilities": ["browser_control", "web_navigation"],
        "trust_tier": "tier_2",
        "provider_affinity": "any",
    },
)
def browser_open(url: str) -> str:
    sid = _launch_session(url)
    return f"Browser opened. session_id={sid}  initial_url={url}"


@tool(
    name="browser_navigate",
    description="Navigate the open browser to a new URL.",
    manifest={
        "category": "browser",
        "action_class": "reversible",
        "capabilities": ["browser_control", "web_navigation"],
        "trust_tier": "tier_2",
        "provider_affinity": "any",
    },
)
def browser_navigate(session_id: str, url: str) -> str:
    s = _get_session(session_id)
    _submit(s, lambda p, u: p.goto(u, wait_until="domcontentloaded", timeout=30000), url)
    return f"Navigated to {url}"


@tool(
    name="browser_click",
    description="Click in the browser using a CSS selector OR pixel coordinates (x, y).",
    manifest={
        "category": "browser",
        "action_class": "reversible",
        "capabilities": ["browser_control"],
        "trust_tier": "tier_2",
        "provider_affinity": "any",
    },
)
def browser_click(session_id: str, selector: str = "", x: int = -1, y: int = -1) -> str:
    s = _get_session(session_id)
    if x >= 0 and y >= 0:
        _submit(s, lambda p, xi, yi: p.mouse.click(xi, yi), x, y)
        return f"Clicked at ({x}, {y})"
    elif selector:
        _submit(s, lambda p, sel: p.click(sel, timeout=5000), selector)
        return f"Clicked '{selector}'"
    return "Error: provide selector or x/y"


@tool(
    name="browser_type",
    description="Type text into an input element identified by CSS selector.",
    manifest={
        "category": "browser",
        "action_class": "reversible",
        "capabilities": ["browser_control"],
        "trust_tier": "tier_2",
        "provider_affinity": "any",
    },
)
def browser_type(session_id: str, selector: str, text: str, clear_first: bool = True) -> str:
    s = _get_session(session_id)
    if clear_first:
        _submit(s, lambda p, sel, t: p.fill(sel, t, timeout=5000), selector, text)
    else:
        _submit(s, lambda p, sel, t: p.type(sel, t, delay=30), selector, text)
    return f"Typed into '{selector}'"


@tool(
    name="browser_press_key",
    description="Press a keyboard key: Enter, Escape, Tab, ArrowDown, F5, Backspace, etc.",
    manifest={
        "category": "browser",
        "action_class": "reversible",
        "capabilities": ["browser_control"],
        "trust_tier": "tier_2",
        "provider_affinity": "any",
    },
)
def browser_press_key(session_id: str, key: str, selector: str = "") -> str:
    s = _get_session(session_id)
    if selector:
        _submit(s, lambda p, sel, k: p.press(sel, k), selector, key)
    else:
        _submit(s, lambda p, k: p.keyboard.press(k), key)
    return f"Pressed '{key}'"


@tool(
    name="browser_screenshot",
    description="Return a base64-encoded PNG screenshot of the current browser state.",
    manifest={
        "category": "browser",
        "action_class": "read_only",
        "capabilities": ["browser_control", "screenshot"],
        "trust_tier": "tier_1",
        "provider_affinity": "any",
    },
)
def browser_screenshot(session_id: str) -> str:
    s = _get_session(session_id)
    png: bytes = _submit(s, lambda p: p.screenshot(timeout=5000))
    return "data:image/png;base64," + base64.b64encode(png).decode()


@tool(
    name="browser_get_dom",
    description="Get visible text (text_only=True) or HTML of the current page. Truncated to 8000 chars.",
    manifest={
        "category": "browser",
        "action_class": "read_only",
        "capabilities": ["browser_control", "dom_access"],
        "trust_tier": "tier_1",
        "provider_affinity": "any",
    },
)
def browser_get_dom(session_id: str, selector: str = "body", text_only: bool = True) -> str:
    s = _get_session(session_id)
    sel = selector or "body"
    if text_only:
        content: str = _submit(s, lambda p, sel: p.inner_text(sel), sel)
    else:
        content = _submit(s, lambda p, sel: p.inner_html(sel), sel)
    if len(content) > 8000:
        content = content[:8000] + "\n… [truncated]"
    return content


@tool(
    name="browser_run_js",
    description="Execute JavaScript in the browser page and return the result.",
    manifest={
        "category": "browser",
        "action_class": "dangerous",
        "capabilities": ["browser_control", "code_execution"],
        "trust_tier": "tier_3",
        "provider_affinity": "any",
    },
)
def browser_run_js(session_id: str, code: str) -> str:
    s = _get_session(session_id)
    return str(_submit(s, lambda p, c: p.evaluate(c), code))


@tool(
    name="browser_get_url",
    description="Return the current URL and page title of the open browser.",
    manifest={
        "category": "browser",
        "action_class": "read_only",
        "capabilities": ["browser_control"],
        "trust_tier": "tier_1",
        "provider_affinity": "any",
    },
)
def browser_get_url(session_id: str) -> str:
    s = _get_session(session_id)
    url = _submit(s, lambda p: p.url)
    title = _submit(s, lambda p: p.title())
    return f"URL={url}  Title={title}"


@tool(
    name="browser_scroll",
    description="Scroll the page or a specific element up/down by a pixel amount.",
    manifest={
        "category": "browser",
        "action_class": "reversible",
        "capabilities": ["browser_control"],
        "trust_tier": "tier_1",
        "provider_affinity": "any",
    },
)
def browser_scroll(session_id: str, direction: str = "down", pixels: int = 400, selector: str = "") -> str:
    s = _get_session(session_id)
    direction = direction.lower()
    delta_y = pixels if direction == "down" else -pixels
    delta_x = 0
    if direction in ("right", "left"):
        delta_x = pixels if direction == "right" else -pixels
        delta_y = 0
    if selector:
        _submit(s, lambda p, sel, dx, dy: p.eval_on_selector(
            sel,
            "(el, [dx, dy]) => el.scrollBy(dx, dy)",
            [delta_x, delta_y],
        ), selector, delta_x, delta_y)
        return f"Scrolled element '{selector}' {direction} by {pixels}px"
    else:
        _submit(s, lambda p, dx, dy: p.evaluate("([dx, dy]) => window.scrollBy(dx, dy)", [dx, dy]), delta_x, delta_y)
        return f"Scrolled page {direction} by {pixels}px"


@tool(
    name="browser_wait",
    description=(
        "Wait for a CSS selector to appear on the page (with optional timeout), "
        "or simply sleep for a given number of milliseconds. "
        "Use before screenshot after a navigation or form submission."
    ),
    manifest={
        "category": "browser",
        "action_class": "read_only",
        "capabilities": ["browser_control"],
        "trust_tier": "tier_1",
        "provider_affinity": "any",
    },
)
def browser_wait(
    session_id: str,
    selector: str = "",
    sleep_ms: int = 0,
    timeout_ms: int = 10000,
) -> str:
    s = _get_session(session_id)
    if selector:
        _submit(
            s,
            lambda p, sel, t: p.wait_for_selector(sel, timeout=t),
            selector,
            timeout_ms,
            timeout=timeout_ms / 1000 + 5,
        )
        return f"Element '{selector}' appeared."
    elif sleep_ms > 0:
        _submit(s, lambda p, ms: p.wait_for_timeout(ms), sleep_ms, timeout=sleep_ms / 1000 + 5)
        return f"Waited {sleep_ms}ms."
    return "No wait condition specified."


@tool(
    name="browser_close",
    description="Close a browser session and release its resources.",
    manifest={
        "category": "browser",
        "action_class": "reversible",
        "capabilities": ["browser_control"],
        "trust_tier": "tier_1",
        "provider_affinity": "any",
    },
)
def browser_close(session_id: str) -> str:
    with _sessions_lock:
        s = _sessions.get(session_id)
    if s is None:
        return f"Session '{session_id}' not found."
    s["stream_active"] = False
    s["_queue"].put(None)
    return f"Browser session {session_id} closed."
