"""System control routes."""
import os
import sys
import signal
import threading
from dataclasses import asdict
from flask import Blueprint, jsonify, request
from web.utils import state
from core.self_model import build_self_model
from core.session_memory import get_engagement
from core.audit import read_audit, audit_event
from core.self_edit import apply_self_edit, SelfEditError

system_bp = Blueprint('system', __name__, url_prefix='/api')


@system_bp.route('/system')
def get_system_info():
    """Quick system info for the dashboard."""
    if not state.monitor:
        return jsonify({"error": "Monitor not initialized"}), 500
    
    stats = state.monitor.get_stats()
    stats["agent_pool"] = state.pool_stats()
    return jsonify(stats)


@system_bp.route('/shutdown', methods=['POST'])
def shutdown_server():
    """Shut down the web server process."""
    threading.Timer(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    return jsonify({"ok": True})


@system_bp.route('/restart', methods=['POST'])
def restart_server():
    """Restart the web server by spawning a fresh process and exiting cleanly."""
    def _do_restart():
        import time
        import subprocess
        time.sleep(0.8)
        # Spawn a new independent process so the old socket is fully released first
        subprocess.Popen(
            [sys.executable] + sys.argv,
            close_fds=True,
            cwd=os.getcwd(),
        )
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_do_restart, daemon=True).start()
    return jsonify({"ok": True})


@system_bp.route('/self-model')
def self_model():
    """Return a current self-model snapshot and synthesized conclusion."""
    snapshot = build_self_model(state.agent, state.config or {})
    conv_id = state.current_conv_id
    snapshot["session_memory"] = get_engagement(conv_id) if conv_id else None
    return jsonify(snapshot)


@system_bp.route('/audit')
def audit_feed():
    """Return recent append-only audit events."""
    try:
        limit = int(request.args.get("limit", 200))
    except Exception:
        limit = 200
    return jsonify({"events": read_audit(limit)})


@system_bp.route('/memory')
def memory_snapshot():
    """Return a full snapshot of all agent memory layers."""
    if not state.agent:
        return jsonify({"error": "Agent not initialized"}), 500

    # ── Episodic memory ────────────────────────────────────────────────────
    em = state.agent.episodic_memory
    episodes_raw = em.recent(30)
    episodes = []
    for ep in reversed(episodes_raw):  # newest first
        episodes.append({
            "timestamp": ep.timestamp,
            "task_summary": ep.task_summary,
            "task_type": ep.task_type,
            "strategy": ep.strategy,
            "tools_used": ep.tools_used,
            "provider_model": ep.provider_model,
            "outcome": ep.outcome,
            "quality_score": ep.quality_score,
            "lessons": ep.lessons,
        })

    # ── Fact memory ────────────────────────────────────────────────────────
    fm = state.agent.fact_memory
    fm._load()
    global_facts = []
    for f in reversed(fm._global_facts[-100:]):
        global_facts.append({
            "subject": f.subject,
            "predicate": f.predicate,
            "value": f.value,
            "source": f.source,
            "confidence": f.confidence,
            "timestamp": f.timestamp,
        })

    # Current-engagement facts
    engagement_facts = []
    conv_id = state.current_conv_id
    if conv_id:
        for f in fm._engagement_facts.get(conv_id, []):
            engagement_facts.append({
                "subject": f.subject,
                "predicate": f.predicate,
                "value": f.value,
                "source": f.source,
                "confidence": f.confidence,
            })

    # ── Strategy memory ────────────────────────────────────────────────────
    strategy_scores = state.agent.strategy_memory.get_all_scores()
    strategy_history = state.agent.strategy_memory.get_history(limit=30)

    # ── Session / engagement memory ────────────────────────────────────────
    session = get_engagement(conv_id) if conv_id else None

    return jsonify({
        "episodic": {
            "count": em.count(),
            "episodes": episodes,
        },
        "facts": {
            "global_count": len(fm._global_facts),
            "global": global_facts,
            "engagement": engagement_facts,
        },
        "strategy": {
            "scores": strategy_scores,
            "history": strategy_history,
        },
        "session": session,
    })


@system_bp.route('/memory/facts', methods=['DELETE'])
def forget_fact():
    """Forget a fact by subject (and optionally predicate)."""
    if not state.agent:
        return jsonify({"error": "Agent not initialized"}), 500
    data = request.get_json() or {}
    subject = data.get("subject", "").strip()
    predicate = data.get("predicate", "").strip() or None
    if not subject:
        return jsonify({"error": "subject required"}), 400
    state.agent.fact_memory.forget(subject, predicate)
    return jsonify({"ok": True})


@system_bp.route('/self-edit', methods=['POST'])
def self_edit():
    """Apply a governed self-edit operation with rollback metadata."""
    data = request.get_json() or {}
    operation = data.get("operation") or {}
    try:
        result = apply_self_edit(state.config, operation)
        audit_event("self_edit_api", {"success": True, "operation": operation})
        return jsonify(result)
    except SelfEditError as e:
        audit_event("self_edit_api", {"success": False, "error": str(e), "operation": operation})
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        audit_event("self_edit_api", {"success": False, "error": str(e), "operation": operation})
        return jsonify({"success": False, "error": str(e)}), 500


@system_bp.route('/escalate', methods=['POST'])
def escalate():
    """Manual escalation override endpoint for operator intervention."""
    data = request.get_json() or {}
    action = str(data.get("action", "review")).strip() or "review"
    reason = str(data.get("reason", "")).strip()
    audit_event("manual_escalation", {"action": action, "reason": reason})
    return jsonify({"ok": True, "action": action, "reason": reason})
