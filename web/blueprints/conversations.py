"""Conversation management routes."""
import uuid
import datetime
from flask import Blueprint, jsonify, request
from web.services import conversation_service
from web.utils import state
from config import SYSTEM_PROMPT
from core.session_memory import clear_engagement

conversations_bp = Blueprint('conversations', __name__, url_prefix='/api/conversations')


@conversations_bp.route('')
def list_conversations():
    """List all saved conversations."""
    return jsonify({"conversations": conversation_service.list_conversations()})


@conversations_bp.route('/<conv_id>')
def get_conversation(conv_id):
    """Get a specific conversation."""
    conv = conversation_service.load_conversation(conv_id)
    if not conv:
        return jsonify({"error": "Not found"}), 404
    return jsonify(conv)


@conversations_bp.route('', methods=['POST'])
def create_conversation():
    """Create a new conversation."""
    conv_id = str(uuid.uuid4())
    data = request.get_json() or {}
    conv = {
        "id": conv_id,
        "title": data.get("title", "New Chat"),
        "created_at": datetime.datetime.now().isoformat(),
        "updated_at": datetime.datetime.now().isoformat(),
        "messages": [],
    }
    conversation_service.save_conversation(conv_id, conv)
    state.set_current_conv_id(conv_id)
    
    # Remove any stale pool agent for a brand-new conversation
    state.remove_agent(conv_id)
    
    return jsonify(conv)


@conversations_bp.route('/<conv_id>', methods=['PUT'])
def update_conversation(conv_id):
    """Update conversation title."""
    data = request.get_json() or {}
    if "title" not in data:
        return jsonify({"error": "Title required"}), 400
    
    success = conversation_service.update_conversation_title(conv_id, data["title"])
    if not success:
        return jsonify({"error": "Not found"}), 404
    
    return jsonify({"success": True})


@conversations_bp.route('/<conv_id>', methods=['DELETE'])
def delete_conversation(conv_id):
    """Remove a conversation from recents while preserving an archived copy."""
    success = conversation_service.archive_conversation(conv_id)
    if not success:
        return jsonify({"error": "Not found"}), 404
    
    if state.current_conv_id == conv_id:
        state.set_current_conv_id(None)
    state.cancel_conv(conv_id, timeout=3.0)
    state.remove_agent(conv_id)
    clear_engagement(conv_id)
    
    return jsonify({"success": True, "archived": True})


@conversations_bp.route('/clear', methods=['POST'])
def clear_recent_conversations():
    """Archive all recent conversations and clear the recent list."""
    archived_ids = conversation_service.clear_recent_conversations()
    
    if state.current_conv_id in archived_ids:
        state.set_current_conv_id(None)
    for conv_id in archived_ids:
        state.cancel_conv(conv_id, timeout=2.0)
        state.remove_agent(conv_id)
        clear_engagement(conv_id)
    
    return jsonify({"success": True, "archived_count": len(archived_ids)})


@conversations_bp.route('/<conv_id>/load', methods=['POST'])
def load_conversation(conv_id):
    """Load a conversation into the agent."""
    conv = conversation_service.load_conversation(conv_id)
    if not conv:
        return jsonify({"error": "Not found"}), 404
    
    state.set_current_conv_id(conv_id)
    clear_engagement(conv_id)
    
    # Rebuild the pool agent's messages from conversation history —
    # but ONLY if the agent is idle. If it's actively running we must
    # not overwrite its messages mid-loop.
    t = state.get_conv_thread(conv_id)
    if t is None or not t.is_alive():
        agent = state.get_agent(conv_id)
        agent.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in conv.get("messages", []):
            agent.messages.append({"role": msg["role"], "content": msg["content"]})
    
    return jsonify({"success": True, "conversation": conv})
