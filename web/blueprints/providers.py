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
    disabled = state.config.get("disabled_providers", [])
    result = []
    for pname in list_providers():
        pconf = state.config.get("providers", {}).get(pname, {})
        result.append({
            "name": pname,
            "model": pconf.get("model", ""),
            "has_key": bool(pconf.get("api_key")) if pname != "copilot" else None,
            "is_current": state.agent and pname in state.agent.provider.name().lower(),
            "disabled": pname in disabled,
        })
    return jsonify(result)


@providers_bp.route('/provider/toggle', methods=['POST'])
def toggle_provider():
    """Enable or disable a provider."""
    data = request.get_json() or {}
    provider = data.get("provider", "").strip()
    if not provider:
        return jsonify({"error": "Provider name required"}), 400
    if provider not in list_providers():
        return jsonify({"error": f"Unknown provider: {provider}"}), 400

    disabled = state.config.setdefault("disabled_providers", [])
    if provider in disabled:
        disabled.remove(provider)
        enabled = True
    else:
        # Don't allow disabling the last enabled provider
        all_providers = list_providers()
        still_enabled = [p for p in all_providers if p not in disabled and p != provider]
        if not still_enabled:
            return jsonify({"error": "Cannot disable all providers — at least one must remain enabled"}), 400
        disabled.append(provider)
        enabled = False

    save_config(state.config)
    return jsonify({"success": True, "provider": provider, "enabled": enabled})


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


@providers_bp.route('/xai/token-status')
def xai_token_status():
    """Get xAI API key status, session usage, and rate limits."""
    import requests as _req

    grok_conf = (state.config or {}).get("providers", {}).get("grok", {})
    api_key = grok_conf.get("api_key", "")
    base_url = grok_conf.get("base_url", "https://api.x.ai/v1")

    result = {
        "key_configured": bool(api_key),
        "key_valid": False,
        "key_preview": f"...{api_key[-6:]}" if len(api_key) > 6 else ("***" if api_key else ""),
        "models_available": [],
        "rate_limits": {},
        "session_usage": {},
    }

    if not api_key:
        return jsonify(result)

    # 1) Validate key & list available models
    try:
        resp = _req.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            result["key_valid"] = True
            models_data = resp.json().get("data", [])
            result["models_available"] = sorted([m.get("id", "") for m in models_data if m.get("id")])
        elif resp.status_code == 401:
            result["key_error"] = "Invalid or expired API key"
        elif resp.status_code == 429:
            result["key_valid"] = True  # key is valid, just rate-limited
            result["key_error"] = "Rate limited"
        else:
            result["key_error"] = f"HTTP {resp.status_code}"
    except _req.ConnectionError:
        result["key_error"] = "Cannot reach api.x.ai"
    except _req.Timeout:
        result["key_error"] = "Request timed out"
    except Exception as e:
        result["key_error"] = str(e)[:100]

    # 2) Session usage from the Grok provider instance
    if state.agent and hasattr(state.agent, 'provider'):
        prov = state.agent.provider
        if hasattr(prov, 'get_session_usage'):
            result["session_usage"] = prov.get_session_usage()
        if hasattr(prov, 'get_rate_limits'):
            result["rate_limits"] = prov.get_rate_limits()

    return jsonify(result)
