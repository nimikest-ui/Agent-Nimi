Auto-Evaluator
──────────────
Scores LLM responses on quality, latency, and cost.
Quality is estimated via heuristics (no second LLM call needed).
When heuristic quality is low and semantic evaluation is enabled,
a cheap LLM judge provides a second opinion (Phase 6).
"""
import json
import math
import re
import time

# Rough cost per 1K tokens (output), USD
# Used only for relative scoring — doesn't need to be exact
# Prices sourced from xAI docs (docs.x.ai/docs/models) — output price / 1M → /1000
MODEL_COST_PER_1K: dict[str, float] = {
    # Grok — grok-4.20 family ($6/1M out = $0.006/1K)
    "grok-4.20": 0.006,
    "grok-4.20-0309-reasoning": 0.006,
    "grok-4.20-0309-non-reasoning": 0.006,
    "grok-4.20-multi-agent-0309": 0.006,
    # Grok — grok-4 family
    "grok-4": 0.015,      # $15/1M out (same tier as grok-3)
    "grok-4-fast": 0.0005, # $0.50/1M out (alias: grok-4-fast-reasoning)
    # Grok — grok-4-1-fast family ($0.50/1M out = $0.0005/1K)
    "grok-4-1-fast-reasoning": 0.0005,
    "grok-4-1-fast-non-reasoning": 0.0005,
    # Grok — grok-3 family
    "grok-3": 0.015,           # $15/1M out
    "grok-3-fast": 0.015,      # alias for grok-3, same price
    "grok-3-mini": 0.0005,     # $0.50/1M out
    "grok-3-mini-fast": 0.0005, # alias for grok-3-mini, same price
    # Grok — grok-2 family ($10/1M out)
    "grok-2-1212": 0.010,
    "grok-2-vision-1212": 0.010,
    "grok-vision-beta": 0.010,
    "grok-beta": 0.010,
    # OpenRouter pass-through estimates
    "gpt-4o": 0.015,
    "gpt-4o-mini": 0.003,
    "gpt-4-turbo": 0.030,
    "claude-3.5-sonnet": 0.015,
    "claude-3-opus": 0.075,
    "claude-3-haiku": 0.001,
    "llama-3-70b-instruct": 0.001,
    "llama-3.1-405b-instruct": 0.005,
    "deepseek-chat": 0.001,
    "deepseek-r1": 0.003,
    "gemini-pro-1.5": 0.007,
    "mistral-large": 0.008,
    # Copilot CLI models - rough relative estimates only
    "claude-sonnet-4.5": 0.015,
    "claude-sonnet-4.6": 0.018,
    "claude-haiku-4.5": 0.001,
    "gpt-5.2": 0.020,
    "gpt-5.3-codex": 0.025,
}

# GitHub Copilot premium request multipliers for paid plans.
# 0 means the model is included and does not consume premium requests on Pro.
COPILOT_PREMIUM_MULTIPLIER: dict[str, float] = {
    "gpt-4.1": 0.0,
    "gpt-4o": 0.0,
    "gpt-5-mini": 0.0,
    "claude-haiku-4.5": 0.33,
    "gpt-5.1-codex-mini": 0.33,
    "grok-code-fast-1": 0.25,
    "claude-sonnet-4": 1.0,
    "claude-sonnet-4.5": 1.0,
    "claude-sonnet-4.6": 1.0,
    "gpt-5.1": 1.0,
    "gpt-5.2": 1.0,
    "gpt-5.2-codex": 1.0,
    "gpt-5.3-codex": 1.0,
    "gpt-5.4": 1.0,
    "claude-opus-4.5": 3.0,
    "claude-opus-4.6": 3.0,
}


def get_copilot_multiplier(model: str) -> float:
    """Return the Copilot premium-request multiplier for a model."""
    model_short = (model.split("/")[-1] if model else "").lower()
    mult = COPILOT_PREMIUM_MULTIPLIER.get(model_short)
    if mult is None:
        for key, value in COPILOT_PREMIUM_MULTIPLIER.items():
            if key in model_short or model_short in key:
                mult = value
                break
    return 1.0 if mult is None else float(mult)


class AutoEvaluator:
    """Evaluate an LLM response and return normalized scores."""

    def evaluate(
        self,
        prompt: str,
        response: str,