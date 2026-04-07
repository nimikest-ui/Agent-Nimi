"""
Smart Router
────────────
Picks the best provider + model for each incoming task based on
learned scores from the memory store, with fallback to a sensible
priority order when insufficient data exists.

Routes:
  Incoming prompt → classify task → check memory → pick best model
                                                  → fallback priority
"""
import time
from typing import Generator

from providers import get_provider, list_providers, LLMProvider
from config import save_config, get_copilot_budget, add_copilot_usage, get_copilot_remaining
from tools.registry import discover_tools
from .memory import LearningMemory
from .evaluator import AutoEvaluator, get_copilot_multiplier


# Default priority when the router has no learned data for a task type.
# Provider → list of models to try in order.
DEFAULT_PRIORITY = {
    "grok": ["grok-4.20-0309-reasoning", "grok-4-1-fast-reasoning", "grok-4-fast-reasoning", "grok-3-mini"],
    "copilot": ["claude-sonnet-4.5", "claude-sonnet-4.6", "gpt-5.3-codex"],
}

# For certain task types, prefer a specific provider first.
# Seeded from the cybersecurity fit diagram (local_ai_cybersecurity_fit.html):
#   LEFT column  → fits on 4 GB VRAM → Ollama first
#   RIGHT column → needs large context / world knowledge → Grok / OpenRouter first
TASK_PREFERENCES = {
    # ── Coding tasks → Copilot first, Grok fallback ──────────────────────────────────
    "code":         ["copilot", "grok"],
    "debug":        ["copilot", "grok"],
    "refactor":     ["copilot", "grok"],
    "test":         ["copilot", "grok"],
    "architecture": ["copilot", "grok"],

    # ── Everything else → Grok primary, Copilot fallback ─────────────────────────────
    "log_triage":    ["grok", "copilot"],
    "yara_sigma":    ["grok", "copilot"],
    "cve_summar":    ["grok", "copilot"],
    "phishing":      ["grok", "copilot"],
    "traffic":       ["grok", "copilot"],
    "sysadmin":      ["grok", "copilot"],
    "recon":         ["grok", "copilot"],
    "scan":          ["grok", "copilot"],
    "malware_re":    ["grok", "copilot"],
    "ti_synthesis":  ["grok", "copilot"],
    "exploit_chain": ["grok", "copilot"],
    "ir_report":     ["grok", "copilot"],
    "exploit":       ["grok", "copilot"],
    "privesc":       ["grok", "copilot"],
    "analysis":      ["grok", "copilot"],
    "password":      ["grok", "copilot"],
    "web":           ["grok", "copilot"],

    # Default
    "_default": ["grok", "copilot"],
}


class SmartRouter:
    """Routes prompts to the best available provider + model."""

    def __init__(self, config: dict, memory: LearningMemory = None, evaluator: AutoEvaluator = None):
        self.config = config
        self.memory = memory or LearningMemory()
        self.evaluator = evaluator or AutoEvaluator()
        self._enabled = True
        self._current_provider: LLMProvider | None = None
        self._current_provider_name: str = ""
        self._current_model: str = ""

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, val: bool):
        self._enabled = val

    def name(self) -> str:
        """Return display name of the current routed provider."""
        if self._current_provider:
            return f"Router → {self._current_provider_name}:{self._current_model}"
        return "Router (idle)"

    def route(self, prompt: str) -> tuple[str, str, LLMProvider]:
        """Decide which provider + model to use for this prompt.
        
        Returns: (provider_name, model, provider_instance)
        """
        task_type = self.evaluator.classify_task(prompt)

        # 1) Check learned memory
        best = self.memory.best_for(task_type)
        if best and best["n"] >= 3:
            provider_name = best["provider"]
            model = best["model"]
            prov = self._make_provider(provider_name, model, task_type)
            if prov:
                self._current_provider = prov
                self._current_provider_name = provider_name
                self._current_model = getattr(prov, "model", model)
                return provider_name, model, prov

        # 2) Fallback to task-based preference order
        pref_order = TASK_PREFERENCES.get(task_type, TASK_PREFERENCES["_default"])
        for pname in pref_order:
            prov = self._try_provider(pname, task_type)
            if prov:
                self._current_provider = prov
                self._current_provider_name = pname
                self._current_model = getattr(prov, "model", self.config["providers"].get(pname, {}).get("model", ""))
                return pname, self._current_model, prov

        # 3) Absolute fallback — try anything that's configured
        for pname in list_providers():
            prov = self._try_provider(pname, task_type)
            if prov:
                self._current_provider = prov
                self._current_provider_name = pname
                self._current_model = getattr(prov, "model", self.config["providers"].get(pname, {}).get("model", ""))
                return pname, self._current_model, prov

        raise RuntimeError("No LLM provider available. Check your config & API keys.")

    # ── Graceful Degradation (Phase 10.1) ─────────────────────────────────

    def degrade(self, failed_provider: str, prompt: str,
                stream_callback=None) -> tuple[str, str, LLMProvider]:
        """Switch away from a provider that just failed mid-conversation.

        Walks the task preference chain (skipping ``failed_provider``) and
        returns the first healthy alternative.  Emits an SSE event so the
        UI can inform the user about the transparent fallback.

        Raises ``RuntimeError`` if no alternative is found.
        """
        task_type = self.evaluator.classify_task(prompt)
        pref_order = TASK_PREFERENCES.get(task_type, TASK_PREFERENCES["_default"])
        tried: list[str] = [failed_provider]

        from core.audit import audit_event
        audit_event("provider_degradation", {
            "failed": failed_provider,
            "task_type": task_type,
        })

        # Try preference chain (skip the broken provider)
        for pname in pref_order:
            if pname in tried:
                continue
            prov = self._try_provider(pname, task_type)
            if prov:
                self._current_provider = prov
                self._current_provider_name = pname
                self._current_model = getattr(
                    prov, "model",
                    self.config["providers"].get(pname, {}).get("model", ""),
                )
                audit_event("provider_degraded", {
                    "from": failed_provider,
                    "to": pname,
                    "model": self._current_model,
                })
                if stream_callback:
                    stream_callback({
                        "event": "provider_degraded",
                        "from": failed_provider,
                        "to": pname,
                        "model": self._current_model,
                    })
                return pname, self._current_model, prov
            tried.append(pname)

        # Absolute fallback
        for pname in list_providers():
            if pname in tried:
                continue
            prov = self._try_provider(pname, task_type)
            if prov:
                self._current_provider = prov
                self._current_provider_name = pname
                self._current_model = getattr(
                    prov, "model",
                    self.config["providers"].get(pname, {}).get("model", ""),
                )
                audit_event("provider_degraded", {
                    "from": failed_provider,
                    "to": pname,
                    "model": self._current_model,
                })
                if stream_callback:
                    stream_callback({
                        "event": "provider_degraded",
                        "from": failed_provider,
                        "to": pname,
                        "model": self._current_model,
                    })
                return pname, self._current_model, prov

        raise RuntimeError(
            f"All providers failed after {failed_provider} went down. "
            "No LLM backends available."
        )

    def route_subtask(self, task_type: str, prompt: str = "") -> tuple[str, str, LLMProvider]:
        """Route a pre-classified subtask type to provider/model.

        Used by multiagent orchestration where classification is already done.
        Returns: (provider_name, model, provider_instance)
        """
        pref_order = self._provider_order_for_task(task_type)
        for pname in pref_order:
            prov = self._try_provider(pname, task_type)
            if prov:
                self._current_provider = prov
                self._current_provider_name = pname
                self._current_model = getattr(prov, "model", self.config["providers"].get(pname, {}).get("model", ""))
                return pname, self._current_model, prov

        for pname in list_providers():
            prov = self._try_provider(pname, task_type)
            if prov:
                self._current_provider = prov
                self._current_provider_name = pname
                self._current_model = getattr(prov, "model", self.config["providers"].get(pname, {}).get("model", ""))
                return pname, self._current_model, prov

        raise RuntimeError(f"No provider available for subtask: {task_type}")

    def chat(self, messages: list[dict], stream: bool = True) -> str | Generator[str, None, None]:
        """Proxy chat to the currently routed provider."""
        if self._current_provider is None:
            raise RuntimeError("Router has no active provider. Call route() first.")
        return self._current_provider.chat(messages, stream=stream)

    def evaluate_and_learn(self, prompt: str, response: str,
                            latency_seconds: float,
                            tool_calls: int = 0, tool_successes: int = 0):
        """Evaluate a completed response and update the memory store."""
        scores = self.evaluator.evaluate(
            prompt=prompt,
            response=response,
            provider=self._current_provider_name,
            model=self._current_model,
            latency_seconds=latency_seconds,
            tool_calls=tool_calls,
            tool_successes=tool_successes,
        )
        self.memory.record(
            task_type=scores["task_type"],
            provider=self._current_provider_name,
            model=self._current_model,
            quality=scores["quality"],
            latency=scores["latency"],
            cost=scores["cost"],
        )
        if self._current_provider_name == "copilot":
            budget = add_copilot_usage(self.config, get_copilot_multiplier(self._current_model))
            self.config["copilot_budget"] = budget
            save_config(self.config)
        return scores

    def get_stats(self) -> dict:
        """Return router stats for the UI."""
        return {
            "enabled": self._enabled,
            "current_provider": self._current_provider_name,
            "current_model": self._current_model,
            "scores": self.memory.get_all_scores(),
            "history": self.memory.get_history(30),
        }

    def explain_route(self, prompt: str) -> dict:
        """Return a human-readable explanation of how a prompt would be routed.

        Does NOT actually switch the current provider — purely informational.
        Used by the web UI and reasoning-trace for transparency.
        """
        task_type = self.evaluator.classify_task(prompt)
        static_pref = list(TASK_PREFERENCES.get(task_type, TASK_PREFERENCES["_default"]))

        # Check learned memory
        best = self.memory.best_for(task_type)
        used_learning = bool(best and best.get("n", 0) >= 3)

        if used_learning:
            chosen = best["provider"]
            reason = (
                f"Learned preference: {chosen} scored best for '{task_type}' "
                f"over {best['n']} observations (EWMA quality={best.get('quality', '?'):.2f})"
            )
        else:
            # Pick the first available from static preferences
            chosen = ""
            for pname in static_pref:
                if pname in self.config.get("providers", {}):
                    chosen = pname
                    break
            if not chosen and self.config.get("providers"):
                chosen = next(iter(self.config["providers"]))
            reason = (
                f"Static preference for '{task_type}': {static_pref}. "
                f"Selected first available: {chosen}"
            )

        return {
            "task_type": task_type,
            "static_preference": static_pref,
            "learned_best": best,
            "decision": "learned" if used_learning else "static",
            "chosen_provider": chosen,
            "reason": reason,
        }

    # ─── Internals ───

    def _is_disabled(self, provider_name: str) -> bool:
        """Check if a provider has been disabled by the user."""
        return provider_name in self.config.get("disabled_providers", [])

    def _make_provider(self, provider_name: str, model: str, task_type: str | None = None) -> LLMProvider | None:
        """Create a provider instance with a specific model override."""
        if self._is_disabled(provider_name):
            return None
        pconf = self.config.get("providers", {}).get(provider_name)
        if not pconf:
            return None
        # For remote API providers, require an API key. Copilot authenticates via local CLI.
        if provider_name not in {"copilot"} and not pconf.get("api_key"):
            return None
        # Override model
        pconf_copy = dict(pconf)
        pconf_copy["model"] = self._resolve_provider_model(provider_name, model, task_type)
        try:
            return get_provider(provider_name, pconf_copy)
        except Exception:
            return None

    def _try_provider(self, provider_name: str, task_type: str | None = None) -> LLMProvider | None:
        """Try to create a provider with its configured model and test connection."""
        if self._is_disabled(provider_name):
            return None
        pconf = self.config.get("providers", {}).get(provider_name)
        if not pconf:
            return None
        if provider_name not in {"copilot"} and not pconf.get("api_key"):
            return None
        try:
            pconf_copy = dict(pconf)
            pconf_copy["model"] = self._resolve_provider_model(provider_name, pconf.get("model", ""), task_type)
            prov = get_provider(provider_name, pconf_copy)
            # Quick provider connection test.
            if prov.test_connection():
                return prov
        except Exception:
            pass
        return None

    def _resolve_provider_model(self, provider_name: str, model: str, task_type: str | None = None) -> str:
        """Select the effective model for a provider, applying Copilot quota policy.

        If the user has explicitly set a model (non-empty), that choice is always
        respected.  Budget-based auto-selection only kicks in when no model is set.
        """
        if provider_name == "copilot":
            if model:
                # User explicitly selected a model — honour it.
                return model
            return self._select_copilot_model(task_type)
        return model

    def _provider_order_for_task(self, task_type: str) -> list[str]:
        """Build provider order from static preferences plus tool discovery metadata."""
        base = list(TASK_PREFERENCES.get(task_type, TASK_PREFERENCES["_default"]))
        capability = self._task_capability(task_type)
        trust_tier = self._task_trust_tier(task_type)
        discovered = discover_tools(capability=capability, trust_tier=trust_tier)

        discovered_affinity = []
        for item in discovered:
            affinity = str((item.get("manifest") or {}).get("provider_affinity", "")).strip().lower()
            if affinity and affinity != "any" and affinity not in discovered_affinity:
                discovered_affinity.append(affinity)

        merged = [p for p in discovered_affinity if p in self.config.get("providers", {})]
        merged.extend([p for p in base if p not in merged])
        return merged

    @staticmethod
    def _task_capability(task_type: str) -> str:
        """Normalize task_type into manifest capability labels."""
        aliases = {
            "summarize": "analysis",
            "reason": "analysis",
            "refactor": "code",
            "debug": "code",
            "test": "code",
        }
        normalized = (task_type or "").strip().lower()
        return aliases.get(normalized, normalized)

    @staticmethod
    def _task_trust_tier(task_type: str) -> str:
        """Infer minimum trust tier for task execution."""
        task = (task_type or "").strip().lower()
        tier2_tasks = {
            "exploit",
            "privesc",
            "scan",
            "recon",
            "sysadmin",
            "password",
            "web",
            "malware_re",
            "exploit_chain",
        }
        return "tier_2" if task in tier2_tasks else "tier_1"

    def _select_copilot_model(self, task_type: str | None = None) -> str:
        """Pick a Copilot model based on remaining Pro premium-request quota."""
        budget = get_copilot_budget(self.config)
        remaining = get_copilot_remaining(self.config)
        if remaining <= 0:
            fallbacks = budget.get("fallback_models") or ["gpt-4.1", "gpt-4o", "gpt-5-mini"]
            return fallbacks[0]
        if remaining <= float(budget.get("phase2_remaining_threshold", 60.0)):
            return budget.get("phase2_model", "claude-haiku-4.5")
        return budget.get("phase1_model", "claude-sonnet-4.5")
