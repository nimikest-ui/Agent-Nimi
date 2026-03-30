"""Router management routes."""
from flask import Blueprint, jsonify, request
from web.utils import state

router_bp = Blueprint('router', __name__, url_prefix='/api/router')


@router_bp.route('/stats')
def get_router_stats():
    """Get smart router statistics."""
    if not state.agent or not state.agent.router:
        return jsonify({"enabled": False})
    
    stats = state.agent.router_stats() or {}
    return jsonify({
        "enabled": state.agent.router.enabled,
        "active": state.agent.routing_active,
        "scores": stats.get("scores", {}),
        "history": stats.get("history", [])
    })


@router_bp.route('/toggle', methods=['POST'])
def toggle_router():
    """Enable or disable smart routing."""
    if not state.agent:
        return jsonify({"error": "No agent initialized"}), 500
    
    data = request.get_json() or {}
    enable = data.get("enable", True)
    
    if enable:
        state.agent.enable_routing()
    else:
        state.agent.disable_routing()
    
    return jsonify({
        "success": True,
        "enabled": state.agent.routing_active if hasattr(state.agent, 'routing_active') else False
    })
