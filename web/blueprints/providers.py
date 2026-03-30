"""Provider and model management routes."""
import json
from flask import Blueprint, jsonify, request
from providers import list_providers
from core.provider_check import check_all_providers
from web.services import agent_service
from web.utils import state
from config import save_config, get_copilot_budget, get_copilot_remaining

providers_bp = Blueprint('providers', __name__, url_prefix='/api')


@providers_bp.route('/providers')
def get_providers():
    """List available providers with their configuration."""
    result = []
    for pname in list_providers():
        pconf = state.config.get("providers", {}).get(pname, {})
        result.append({
            "name": pname,
            "model": pconf.get("model", ""),
            "has_key": bool(pconf.get("api_key")) if pname != "copilot" else None,
            "is_current": state.agent and pname in state.agent.provider.name().lower(),
        })
    return jsonify(result)


@providers_bp.route('/provider', methods=['POST'])
def switch_provider():
    """Switch to a different provider."""
    data = request.get_json() or {}
    provider = data.get("provider", "").strip()
    if not provider:
        return jsonify({"error": "Provider name required"}), 400
    
    try:
        agent_service.switch_provider(provider)
        return jsonify({"success": True, "provider": state.agent.provider.name()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@providers_bp.route('/model', methods=['POST'])
def set_model():
    """Change model for current provider."""
    data = request.get_json() or {}
    model = data.get("model", "").strip()
    provider = data.get("provider", "").strip()
    
    if not model:
        return jsonify({"error": "Model name required"}), 400
    
    try:
        agent_service.set_model(model, provider)
        return jsonify({"success": True, "model": model})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@providers_bp.route('/models')
def list_models():
    """List available models for each provider."""
    models_by_provider = {}
    
    # Grok models
    models_by_provider["grok"] = [
        {"name": "grok-beta", "provider": "grok"},
        {"name": "grok-vision-beta", "provider": "grok"},
    ]
    
    # Copilot models
    models_by_provider["copilot"] = [
        {"name": "gpt-4.1", "provider": "copilot"},
        {"name": "gpt-4o", "provider": "copilot"},
        {"name": "gpt-5-mini", "provider": "copilot"},
        {"name": "claude-haiku-4.5", "provider": "copilot"},
        {"name": "claude-sonnet-4.5", "provider": "copilot"},
        {"name": "claude-sonnet-4.6", "provider": "copilot"},
        {"name": "gpt-5.2", "provider": "copilot"},
        {"name": "gpt-5.3-codex", "provider": "copilot"},
    ]
    
    return jsonify(models_by_provider)


@providers_bp.route('/setkey', methods=['POST'])
def set_api_key():
    """Set API key for current provider."""
    data = request.get_json() or {}
    api_key = data.get("key", "").strip()
    
    if not api_key:
        return jsonify({"error": "API key required"}), 400
    
    try:
        agent_service.set_api_key(api_key)
        connected = state.agent.provider.test_connection() if state.agent else False
        return jsonify({"success": True, "connected": connected})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@providers_bp.route('/status')
def get_status():
    """Get agent and provider status."""
    if not state.agent:
        return jsonify({"error": "No agent initialized"}), 500
    
    provider_info = agent_service.get_provider_info()
    history_summary = state.agent.get_history_summary()
    
    result = {
        "provider": provider_info,
        "history": history_summary,
        "monitor": {
            "running": state.monitor.is_running if state.monitor else False,
            "alert_count": len(state.monitor.alert_log) if state.monitor else 0,
        }
    }
    
    # Router info if available
    if state.agent.router:
        stats = state.agent.router_stats() or {}
        result["router"] = {
            "enabled": state.agent.router.enabled,
            "active": state.agent.routing_active,
            "learned_entries": sum(len(v) for v in stats.get("scores", {}).values()),
        }

    result["copilot_budget"] = {
        **get_copilot_budget(state.config),
        "remaining": get_copilot_remaining(state.config),
    }
    
    return jsonify(result)


@providers_bp.route('/clear', methods=['POST'])
def clear_history():
    """Clear conversation history."""
    if state.agent:
        state.agent.reset_conversation()
    return jsonify({"success": True})


@providers_bp.route('/health')
def provider_health():
    """Deep health-check all providers.  Returns per-provider status."""
    deep = request.args.get("deep", "true").lower() in ("true", "1", "yes")
    results = check_all_providers(state.config or {}, deep=deep)
    return jsonify(results)
