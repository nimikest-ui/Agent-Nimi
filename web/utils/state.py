"""Global state management for web server."""
import queue
import threading
from typing import Optional
from core.agent import AgentNimi
from core.monitor import SystemMonitor

# Global state
config: dict = {}
agent: Optional[AgentNimi] = None
monitor: Optional[SystemMonitor] = None
sessions: dict[str, queue.Queue] = {}
current_conv_id: Optional[str] = None
extension_contexts: dict[str, dict] = {}

# Prevents concurrent agent calls from colliding on shared agent state
agent_lock = threading.Lock()
_active_session_id: Optional[str] = None


def set_active_session(session_id: Optional[str]):
    global _active_session_id
    _active_session_id = session_id


def get_active_session() -> Optional[str]:
    return _active_session_id


def set_agent(new_agent: AgentNimi):
    """Set the global agent instance."""
    global agent
    agent = new_agent


def set_monitor(new_monitor: SystemMonitor):
    """Set the global monitor instance."""
    global monitor
    monitor = new_monitor


def set_config(new_config: dict):
    """Set the global config."""
    global config
    config = new_config


def set_current_conv_id(conv_id: str):
    """Set the current conversation ID."""
    global current_conv_id
    current_conv_id = conv_id


def get_session(session_id: str) -> queue.Queue:
    """Get or create a session queue."""
    if session_id not in sessions:
        sessions[session_id] = queue.Queue()
    return sessions[session_id]


def clear_session(session_id: str):
    """Clear a session queue."""
    if session_id in sessions:
        del sessions[session_id]


def set_extension_context(tab_key: str, context: dict):
    """Store latest extension context for a tab/session key."""
    extension_contexts[tab_key] = context


def get_extension_context(tab_key: str) -> dict:
    """Get latest extension context by tab/session key."""
    return extension_contexts.get(tab_key, {})
