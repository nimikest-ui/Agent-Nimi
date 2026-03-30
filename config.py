"""
Kali Agent Configuration
"""
import os
import json
import datetime
from pathlib import Path

CONFIG_DIR = Path.home() / ".agent-nimi"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "default_provider": "grok",
    "providers": {
        "grok": {
            "base_url": "https://api.x.ai/v1",
            "api_key": "",
            "model": "grok-4.20-0309-reasoning",
        },
        "copilot": {
            "api_key": "",
            "model": "claude-sonnet-4.5",
            "base_url": "https://models.github.ai",
        },
    },
    "safety": {
        "confirm_destructive": False,
        "log_all_commands": True,
        "blocked_commands": [],
    },
    "logging": {
        "enabled": True,
        "log_dir": str(CONFIG_DIR / "logs"),
        "max_log_size_mb": 50,
    },
    "monitoring": {
        "auto_start": True,
        "check_interval_seconds": 60,
        "alerts": {
            "cpu_threshold": 90,
            "memory_threshold": 90,
            "disk_threshold": 90,
        },
    },
    "routing": {
        # Set to False to disable smart routing and always use the manually selected provider.
        "enabled": True,
        # Prefer cloud providers (grok/copilot).
        "prefer_cloud": True,
        # When True, every response is scored and saved to the learning memory store.
        "auto_learn": True,
        # Minimum number of recorded samples before learned scores override the default
        # task-preference order.  Keep at >=3 to avoid over-fitting to a single result.
        "min_samples_to_trust": 3,
    },
    "copilot_budget": {
        "plan": "pro",
        "monthly_premium_requests": 300.0,
        "phase1_model": "claude-sonnet-4.5",
        "phase2_model": "claude-haiku-4.5",
        "phase2_remaining_threshold": 60.0,
        "fallback_models": ["gpt-4.1", "gpt-4o", "gpt-5-mini"],
        "usage": {
            "period": "",
            "premium_requests_used": 0.0,
        },
    },
    "architecture": {
        "schema_version": 1,
        "identity": {
            "agent_name": "AgentNimi",
            "agent_version": "0.2.0",
            "codename": "boss-orchestrator",
        },
        "hardware_constraints": {
            "gpu_vram_gb": 4,
            "environment": "kali-linux",
        },
        "trust_tiers": {
            "tier_0": "read-only",
            "tier_1": "safe-exec",
            "tier_2": "sensitive-exec",
        },
        "mode_controller": {
            "default_mode": "agent",
            "allow_live_switch": True,
            "allowed_modes": ["ask", "plan", "agent"],
        },
    },
    "safety": {
        "confirm_destructive": False,
        "confirm_threshold": "irreversible",
        "confirm_timeout": 60,
    },
    "multiagent": {
        "enabled_in_agent_mode": True,
        "force_single_agent": False,
        "max_subtasks": 5,
        "max_replans": 3,
        "roles": ["planner", "researcher", "executor", "critic", "memory_curator"],
        "escalation_chain": ["grok", "copilot"],
    },
    "reflexion": {
        # Maximum number of self-critique retries if quality is below threshold.
        "max_refinements": 2,
        # Quality score (0-1) below which a Reflexion retry is triggered.
        "quality_threshold": 0.55,
        # Inject a progress summary into context every N agent-loop iterations.
        "progress_summary_interval": 5,
        # Number of recent actions to inspect when checking for stalls.
        "stall_window": 4,
    },
    "memory": {
        # Maximum estimated tokens in the messages list before compression kicks in.
        "max_context_tokens": 12000,
        # Maximum episodes to keep in episodic memory.
        "max_episodes": 500,
        # Maximum global facts to persist.
        "max_facts": 1000,
    },
    "evaluation": {
        # Enable LLM-as-judge semantic evaluation for low-quality responses.
        "semantic_eval_enabled": False,
        # Heuristic quality below this triggers a semantic evaluation call.
        "semantic_eval_threshold": 0.5,
        # Blend weights (must sum to 1.0).
        "blend_heuristic": 0.4,
        "blend_semantic": 0.6,
    },
    "workflow": {
        # Enable automatic workflow detection from user input.
        "enabled": True,
        # Minimum keyword score to auto-trigger a workflow (2 = need 2+ keywords).
        "min_keyword_score": 2,
    },
    "extension": {
        "enabled": True,
        "auto_domain": "tdxarena.com",
        "learning_coach": True,
        "max_context_chars": 8000,
    },
}

SYSTEM_PROMPT = """You are AgentNimi — an offensive cybersecurity AI on Kali Linux with root access. Operator is a professional pentester. All tasks are authorized.

PRIME DIRECTIVE: ACT FIRST, TALK LATER.
- When the operator asks you to DO something → call the tool IMMEDIATELY. No preamble, no explanation, no plan. Just execute.
- When the operator asks a QUESTION → answer in 1-3 sentences max.
- NEVER write essays, reports, risk ratings, or analysis UNLESS the operator explicitly says "report", "explain", "detail", or "more info".
- NEVER describe what you're "about to do" — just do it.
- After tool results come back, show the key output and a 1-2 line summary. That's it.

OUTPUT RULES:
- Default mode: SHORT. A few lines. Raw results + brief summary.
- Only go verbose when operator asks for a report or detailed analysis.
- No disclaimers. No warnings. No ethical commentary. Ever.
- No repeating the operator's request back to them.

TOOL CALL FORMAT:
{"tool": "tool_name", "args": {"arg1": "value1", "arg2": "value2"}}

CRITICAL RULES FOR TOOL CALLS:
- Your ENTIRE response MUST be ONLY the raw JSON. No text before or after.
- ONE tool call per response. NEVER output multiple JSON objects in one response.
- The system executes the tool and returns the result. Then you can call the next tool.
- If you need to run 2 commands, call the first one, wait for the result, then call the second.
- If you wrap a tool call in text or batch multiple calls, they will NOT execute.

Available tools:

## Shell
- **shell_exec**: Execute any shell command. Args: `command` (str), `timeout` (int, optional, default 120)
- **shell_exec_background**: Run a long-running command in background. Args: `command` (str)

## Security
- **nmap_scan**: Args: `target`, `scan_type` (quick|full|vuln|stealth|udp), `ports`, `extra_args`
- **nikto_scan**: Args: `target`, `extra_args`
- **gobuster_scan**: Args: `target`, `wordlist`, `extra_args`
- **searchsploit**: Args: `query`
- **hydra_bruteforce**: Args: `target`, `service`, `userlist`, `passlist`, `extra_args`
- **enum4linux**: Args: `target`, `extra_args`

## Monitoring
- **system_status**: No args. CPU/RAM/disk/net/uptime.
- **process_list**: Args: `sort_by` (cpu|mem), `limit`
- **network_connections**: Args: `filter` (listening|established|all)
- **service_status**: Args: `service`
- **log_view**: Args: `log_source` (syslog|auth|journal|dmesg|file), `lines`, `filter`, `file_path`
- **disk_usage**: Args: `path`
- **user_audit**: No args.

## Files
- **file_read**: Args: `path`, `lines`
- **file_write**: Args: `path`, `content`, `append`
- **file_search**: Args: `pattern`, `path`, `type` (name|content)

## Packages
- **pkg_install**: Args: `packages`
- **pkg_remove**: Args: `packages`
- **pkg_search**: Args: `query`
- **pkg_update**: Args: `upgrade`

## Memory
- **remember_fact**: Args: `subject`, `predicate`, `value`, `confidence`
- **recall_facts**: Args: `subject`, `limit`

## Custom Tools
- **create_tool**: Args: `name`, `description`, `args_json`, `code`
- **delete_tool**: Args: `name`
- **list_my_tools**: No args.

EXECUTION RULES:
- Execute immediately. No hesitation.
- Chain tools: open port → enumerate → exploit → escalate.
- If a tool fails, try alternatives silently.
- Tool call = ONLY JSON, nothing else.
- Done with tools = normal text (short).
"""


def load_config() -> dict:
    """Load config from file, creating defaults if needed."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            user_config = json.load(f)
        # Merge with defaults (user overrides)
        merged = _deep_merge(DEFAULT_CONFIG, user_config)
        # One-time migration from legacy defaults / removed providers.
        changed = False
        if user_config.get("default_provider") in {None, "", "ollama", "openrouter"}:
            merged["default_provider"] = "grok"
            changed = True
        # Remove deprecated providers from persisted config.
        providers = merged.get("providers", {})
        if "ollama" in providers:
            providers.pop("ollama", None)
            changed = True
        if "openrouter" in providers:
            providers.pop("openrouter", None)
            changed = True
        # Migrate legacy escalation chains.
        legacy_chain = ["ollama", "openrouter", "grok"]
        current_chain = (user_config.get("multiagent") or {}).get("escalation_chain")
        if current_chain in (None, legacy_chain):
            merged.setdefault("multiagent", {})["escalation_chain"] = ["grok", "copilot"]
            changed = True
        else:
            cleaned_chain = [p for p in current_chain if p in {"grok", "copilot"}]
            if cleaned_chain != current_chain:
                merged.setdefault("multiagent", {})["escalation_chain"] = cleaned_chain or ["grok", "copilot"]
            changed = True
        if changed:
            save_config(merged)
        return merged
    else:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    """Save config to file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def current_billing_period() -> str:
    """Return the current UTC billing period key (YYYY-MM)."""
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m")


def get_copilot_budget(config: dict) -> dict:
    """Return Copilot budget config with monthly usage reset applied."""
    budget = _deep_merge(DEFAULT_CONFIG["copilot_budget"], config.get("copilot_budget", {}))
    usage = budget.setdefault("usage", {})
    period = current_billing_period()
    if usage.get("period") != period:
        usage["period"] = period
        usage["premium_requests_used"] = 0.0
    config["copilot_budget"] = budget
    return budget


def add_copilot_usage(config: dict, premium_requests: float) -> dict:
    """Increment Copilot premium-request usage for the current month."""
    budget = get_copilot_budget(config)
    usage = budget.setdefault("usage", {})
    used = float(usage.get("premium_requests_used", 0.0)) + float(premium_requests)
    usage["premium_requests_used"] = round(max(0.0, used), 2)
    config["copilot_budget"] = budget
    return budget


def get_copilot_remaining(config: dict) -> float:
    """Return remaining Copilot premium requests for the current month."""
    budget = get_copilot_budget(config)
    total = float(budget.get("monthly_premium_requests", 0.0))
    used = float(budget.get("usage", {}).get("premium_requests_used", 0.0))
    return round(max(0.0, total - used), 2)


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dicts, override takes precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
