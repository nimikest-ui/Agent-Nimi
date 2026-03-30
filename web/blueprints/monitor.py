"""System monitoring routes."""
from flask import Blueprint, jsonify, request
from web.utils import state

monitor_bp = Blueprint('monitor', __name__, url_prefix='/api/monitor')


@monitor_bp.route('/start', methods=['POST'])
def start_monitor():
    """Start the system monitor."""
    if state.monitor:
        state.monitor.start()
    return jsonify({"success": True, "running": True})


@monitor_bp.route('/stop', methods=['POST'])
def stop_monitor():
    """Stop the system monitor."""
    if state.monitor:
        state.monitor.stop()
    return jsonify({"success": True, "running": False})


@monitor_bp.route('/stats')
def get_monitor_stats():
    """Get system monitoring statistics."""
    if not state.monitor:
        return jsonify({"error": "Monitor not initialized"}), 500
    
    stats = state.monitor.get_stats()
    alerts = [f"[{a['type'].upper()}] {a['message']}" for a in state.monitor.get_alerts(10)]
    return jsonify({
        "system": stats,
        "alerts": alerts,
        "running": state.monitor.is_running,
    })


@monitor_bp.route('', methods=['POST'])
def monitor_control():
    """Legacy endpoint for monitor control."""
    data = request.get_json() or {}
    action = data.get("action", "")
    
    if action == "start":
        if state.monitor:
            state.monitor.start()
        return jsonify({"success": True, "running": True})
    elif action == "stop":
        if state.monitor:
            state.monitor.stop()
        return jsonify({"success": True, "running": False})
    
    return jsonify({"error": "Invalid action"}), 400
