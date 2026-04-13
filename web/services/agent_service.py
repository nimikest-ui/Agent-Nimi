"""Agent initialization and management service."""
import logging

from core.agent import AgentNimi
from core.monitor import SystemMonitor
from core.provider_check import startup_check, check_all_providers
from config import load_config, save_config
from web.utils import state

log = logging.getLogger(__name__)


def init_agent(provider_name: str = None):
    """Initialize or reinitialize the agent.
    
    Runs a full provider health-check (non-interactive) and auto-falls
    back to the best working provider when the default is unavailable.
    """
    config = load_config()
    state.set_config(config)

    # Non-interactive health check — picks the best working provider
    chosen, config = startup_check(
        config,
        interactive=False,
        log=lambda *a, **kw: log.info(" ".join(str(x) for x in a)),
    )
    
    pname = provider_name or chosen
    agent = AgentNimi(pname, config)
    
    # Handle copilot provider model normalization — but only when the saved
    # model is empty or not a recognized persona (e.g. "spectre").  Never
    # overwrite a persona name with its underlying real model.
    if pname == "copilot":
        from providers.copilot_provider import CopilotProvider
        saved_model = config["providers"].setdefault("copilot", {}).get("model", "")
        if saved_model not in CopilotProvider._PERSONAS:
            normalized = getattr(agent.provider, "model", "")
            if normalized and saved_model != normalized:
                config["providers"]["copilot"]["model"] = normalized
                save_config(config)
    
    state.set_agent(agent)
    state.set_config(config)
    
    if state.monitor is None:
        monitor = SystemMonitor(config)
        state.set_monitor(monitor)
    
    return agent


def switch_provider(provider_name: str):
    """Switch to a different provider (applies to the default agent + all pool agents)."""
    if state.agent:
        state.agent.switch_provider(provider_name)
    # Also switch any pooled agents
    with state._pool_lock:
        for ag in state._agents.values():
            try:
                ag.switch_provider(provider_name)
            except Exception:
                pass
    state.config["default_provider"] = provider_name
    save_config(state.config)
    return state.agent


def set_model(model_name: str, provider_name: str = None):
    """Set the model for a provider."""
    pname = provider_name
    if not pname:
        if state.agent and state.agent.provider:
            provider_label = state.agent.provider.name().lower()
            for candidate in state.config.get("providers", {}).keys():
                if candidate in provider_label:
                    pname = candidate
                    break
        pname = pname or state.config.get("default_provider", "grok")
    state.config["providers"][pname]["model"] = model_name
    save_config(state.config)
    if state.agent:
        state.agent.switch_provider(pname)


def set_api_key(api_key: str, provider_name: str = None):
    """Set the API key for a provider."""
    pname = provider_name or state.config.get("default_provider", "grok")
    state.config["providers"][pname]["api_key"] = api_key
    save_config(state.config)
    if state.agent:
        state.agent.switch_provider(pname)


def get_provider_info():
    """Get information about the current provider."""
    if not state.agent:
        return None
    
    # Return the model name as stored in config (preserves persona names like
    # "spectre" instead of returning the normalized underlying model).
    default_prov = state.config.get("default_provider", "")
    config_model = state.config.get("providers", {}).get(default_prov, {}).get("model", "")
    return {
        "name": state.agent.provider.name(),
        "connected": state.agent.provider.test_connection(),
        "model": config_model or getattr(state.agent.provider, "model", ""),
        "routing_active": state.agent.routing_active if hasattr(state.agent, 'routing_active') else False,
    }
