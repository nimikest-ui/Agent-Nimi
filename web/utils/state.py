"""Global state management for web server.

Supports multiple concurrent conversations, each with its own AgentNimi
instance so parallel chats never corrupt each other.
"""
import logging
import queue
import threading
from typing import Optional
from core.agent import AgentNimi
from core.monitor import SystemMonitor

log = logging.getLogger(__name__)

# ── Shared (singleton) state ─────────────────────────────────────────────────
config: dict = {}
monitor: Optional[SystemMonitor] = None

# Legacy single-agent reference — used only by non-chat endpoints
# (providers, tools, etc.) that don't operate per-conversation.
agent: Optional[AgentNimi] = None

# ── Per-conversation agent pool ──────────────────────────────────────────────
_pool_lock = threading.Lock()
_agents: dict[str, AgentNimi] = {}          # conv_id  -> AgentNimi
_threads: dict[str, threading.Thread] = {}  # conv_id  -> worker thread
_conv_sessions: dict[str, str] = {}         # conv_id  -> session_id (SSE queue)

MAX_POOL_SIZE: int = 6   # Evict oldest idle agents beyond this limit

# ── SSE session queues ───────────────────────────────────────────────────────
sessions: dict[str, queue.Queue] = {}
current_conv_id: Optional[str] = None       # last-active conv (UI hint)
extension_contexts: dict[str, dict] = {}
extension_conversations: dict[str, str] = {}

# Legacy compat — kept for the cancel endpoint / steer endpoint
agent_lock = threading.Lock()
_active_session_id: Optional[str] = None
_active_thread: Optional[threading.Thread] = None


# ── Pool helpers ─────────────────────────────────────────────────────────────

def get_agent(conv_id: str) -> AgentNimi:
    """Return the agent for *conv_id*, creating one if needed."""
    with _pool_lock:
        if conv_id in _agents:
            return _agents[conv_id]
    # Create outside lock (constructor may be slow)
    from config import load_config
    cfg = config or load_config()
    pname = cfg.get("default_provider", "grok")
    new_agent = AgentNimi(pname, cfg)
    with _pool_lock:
        # Double-check: another thread may have raced us
        if conv_id in _agents:
            return _agents[conv_id]
        _agents[conv_id] = new_agent
        _evict_idle_locked()
    return new_agent


def remove_agent(conv_id: str):
    """Remove an agent from the pool (e.g. conversation deleted)."""
    with _pool_lock:
        _agents.pop(conv_id, None)
        _threads.pop(conv_id, None)
        _conv_sessions.pop(conv_id, None)


def set_conv_thread(conv_id: str, t: threading.Thread, session_id: str):
    """Track the worker thread + SSE session for a conversation."""
    with _pool_lock:
        _threads[conv_id] = t
        _conv_sessions[conv_id] = session_id


def get_conv_thread(conv_id: str) -> Optional[threading.Thread]:
    with _pool_lock:
        return _threads.get(conv_id)


def cancel_conv(conv_id: str, timeout: float = 8.0) -> bool:
    """Cancel the agent running in *conv_id* and wait for its thread."""
    with _pool_lock:
        ag = _agents.get(conv_id)
        t = _threads.get(conv_id)
        sid = _conv_sessions.get(conv_id)
    if ag:
        ag.cancel()
    if sid:
        poison_session(sid)
    if t and t.is_alive():
        t.join(timeout=timeout)
        return not t.is_alive()
    return True


def _evict_idle_locked():
    """Evict oldest idle agents when the pool exceeds MAX_POOL_SIZE.

    Must be called with _pool_lock held.
    """
    while len(_agents) > MAX_POOL_SIZE:
        # Find a conv whose thread is done (idle)
        for cid in list(_agents):
            t = _threads.get(cid)
            if t is None or not t.is_alive():
                _agents.pop(cid, None)
                _threads.pop(cid, None)
                _conv_sessions.pop(cid, None)
                log.debug("evicted idle agent for conv %s", cid)
                break
        else:
            # All agents are busy — let them be
            break


def pool_stats() -> dict:
    """Return pool diagnostic info."""
    with _pool_lock:
        return {
            "total": len(_agents),
            "active": sum(1 for t in _threads.values() if t and t.is_alive()),
            "idle": sum(1 for cid in _agents if cid not in _threads or not _threads[cid].is_alive()),
            "max": MAX_POOL_SIZE,
        }


# ── Legacy single-agent helpers (backwards compat) ──────────────────────────

def set_active_session(session_id: Optional[str]):
    global _active_session_id
    _active_session_id = session_id


def get_active_session() -> Optional[str]:
    return _active_session_id


def set_active_thread(t: Optional[threading.Thread]):
    global _active_thread
    _active_thread = t


def get_active_thread() -> Optional[threading.Thread]:
    return _active_thread


def cancel_and_wait(timeout: float = 8.0) -> bool:
    """Cancel the running agent and wait for its thread to finish."""
    if agent:
        agent.cancel()
    t = _active_thread
    if t is not None and t.is_alive():
        t.join(timeout=timeout)
        return not t.is_alive()
    return True


def poison_session(session_id: Optional[str]):
    """Push a sentinel into a session queue so its SSE generator exits."""
    if session_id and session_id in sessions:
        try:
            sessions[session_id].put({"type": "error", "message": "Cancelled — new request started"})
            sessions[session_id].put(None)  # sentinel
        except Exception:
            pass


def set_agent(new_agent: AgentNimi):
    """Set the global (default) agent instance."""
    global agent
    agent = new_agent


def set_monitor(new_monitor: SystemMonitor):
    global monitor
    monitor = new_monitor


def set_config(new_config: dict):
    global config
    config = new_config


def set_current_conv_id(conv_id: str):
    global current_conv_id
    current_conv_id = conv_id


def get_session(session_id: str) -> queue.Queue:
    if session_id not in sessions:
        sessions[session_id] = queue.Queue()
    return sessions[session_id]


def clear_session(session_id: str):
    sessions.pop(session_id, None)


def set_extension_context(tab_key: str, context: dict):
    extension_contexts[tab_key] = context


def get_extension_context(tab_key: str) -> dict:
    return extension_contexts.get(tab_key, {})


def set_extension_conversation(tab_key: str, conv_id: str):
    extension_conversations[str(tab_key)] = str(conv_id)


def get_extension_conversation(tab_key: str) -> Optional[str]:
    """Get conversation id bound to a tab/session key."""
    return extension_conversations.get(str(tab_key))
