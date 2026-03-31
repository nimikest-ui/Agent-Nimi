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
