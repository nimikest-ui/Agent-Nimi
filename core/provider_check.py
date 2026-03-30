"""
Startup provider health-check, key prompting, and auto-fallback.

Usage (CLI):
    from core.provider_check import startup_check
    provider_name, config = startup_check(config, interactive=True)

Usage (web / non-interactive):
    from core.provider_check import startup_check
    provider_name, config = startup_check(config, interactive=False)
"""
from __future__ import annotations

import sys
import signal
from typing import Callable

from config import save_config
from providers.base import get_provider, list_providers


# ---------- ANSI helpers (matches main.py palette) ----------
class _C:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


# ---------- preferred fallback order ----------
# grok primary, copilot for code
FALLBACK_ORDER = ["grok", "copilot"]


# ---------- public API ----------

def check_provider(name: str, config: dict, deep: bool = True) -> dict:
    """Check a single provider.  Returns a status dict:
    {
        "name":       str,   # provider name
        "has_key":    bool,  # API key is set (or n/a for copilot)
        "reachable":  bool,  # basic test_connection()
        "working":    bool,  # deep_test_connection() succeeded (if deep=True)
        "model":      str,   # configured model
        "error":      str,   # human-readable error (empty if ok)
    }
    """
    pconf = config.get("providers", {}).get(name, {})
    result = {
        "name": name,
        "has_key": bool(pconf.get("api_key")),
        "reachable": False,
        "working": False,
        "model": pconf.get("model", "?"),
        "error": "",
    }
    try:
        provider = get_provider(name, pconf)
    except Exception as e:
        result["error"] = f"cannot instantiate: {e}"
        return result

    # Quick reachability check (with hard 15s alarm to prevent hangs)
    try:
        old_handler = signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError()))
        signal.alarm(15)
        try:
            result["reachable"] = provider.test_connection()
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
    except (TimeoutError, Exception):
        result["reachable"] = False

    if deep and result["reachable"]:
        ok, err = provider.deep_test_connection()
        result["working"] = ok
        if err:
            result["error"] = err
    elif result["reachable"]:
        result["working"] = True  # skip deep if not requested
    else:
        if not result["has_key"] and name not in ("copilot",):
            result["error"] = "no API key configured"
        elif not result["error"]:
            result["error"] = "server not reachable"

    return result


def check_all_providers(config: dict, deep: bool = True) -> dict[str, dict]:
    """Check every registered provider.  Returns {name: status_dict}."""
    results = {}
    for name in list_providers():
        results[name] = check_provider(name, config, deep=deep)
    return results


def find_best_available(
    config: dict,
    results: dict[str, dict] | None = None,
    order: list[str] | None = None,
) -> str | None:
    """Return the first working provider name from *order*, or None."""
    if results is None:
        results = check_all_providers(config)
    for name in (order or FALLBACK_ORDER):
        st = results.get(name)
        if st and st["working"]:
            return name
    return None


def startup_check(
    config: dict,
    interactive: bool = False,
    log: Callable[..., None] | None = None,
) -> tuple[str, dict]:
    """Run full provider health-check at startup.

    1. Deep-test every provider.
    2. Print a status table.
    3. If *interactive*, prompt for missing API keys.
    4. Pick the best working provider (respecting FALLBACK_ORDER).
    5. Update and save config with the chosen default_provider.

    Returns (chosen_provider_name, updated_config).
    """
    if log is None:
        log = lambda *a, **kw: print(*a, **kw)

    log(f"\n  {_C.CYAN}{_C.BOLD}Provider Health Check{_C.RESET}")
    log(f"  {_C.DIM}{'─' * 58}{_C.RESET}")

    # --- Phase 1: deep-test all ---------------------------------
    results = check_all_providers(config, deep=True)

    for name in FALLBACK_ORDER:
        st = results.get(name)
        if st is None:
            continue
        key_icon = f"{_C.GREEN}✓{_C.RESET}" if st["has_key"] else f"{_C.RED}✗{_C.RESET}"
        if st["working"]:
            status = f"{_C.GREEN}✓ working{_C.RESET}"
        elif st["reachable"]:
            status = f"{_C.YELLOW}⚠ reachable but failed{_C.RESET}"
        else:
            status = f"{_C.RED}✗ offline{_C.RESET}"
        err = f"  {_C.DIM}({st['error']}){_C.RESET}" if st["error"] else ""
        log(f"  {_C.YELLOW}{name:<12}{_C.RESET}  key={key_icon}  model={_C.WHITE}{st['model']:<30}{_C.RESET}  {status}{err}")

    log(f"  {_C.DIM}{'─' * 58}{_C.RESET}")

    # --- Phase 2: interactive key prompting ----------------------
    if interactive:
        for name in FALLBACK_ORDER:
            st = results.get(name)
            if st is None:
                continue
            if st["working"]:
                continue
            if not st["has_key"]:
                try:
                    key = input(f"\n  Enter API key for {_C.BOLD}{name}{_C.RESET} (or Enter to skip): ").strip()
                except (KeyboardInterrupt, EOFError):
                    key = ""
                if key:
                    config["providers"][name]["api_key"] = key
                    save_config(config)
                    # Re-test
                    st2 = check_provider(name, config, deep=True)
                    results[name] = st2
                    if st2["working"]:
                        log(f"  {_C.GREEN}✓ {name} is now working!{_C.RESET}")
                    else:
                        log(f"  {_C.RED}✗ {name} still failed: {st2['error']}{_C.RESET}")

    # --- Phase 3: pick best working provider --------------------
    preferred = config.get("default_provider", "grok")

    # If the user's preferred provider works, keep it
    pref_status = results.get(preferred, {})
    if pref_status.get("working"):
        chosen = preferred
    else:
        chosen = find_best_available(config, results=results)

    if chosen:
        if chosen != preferred:
            log(f"\n  {_C.YELLOW}⚠ Default provider '{preferred}' is unavailable.{_C.RESET}")
            log(f"  {_C.GREEN}↳ Auto-switching to '{chosen}'{_C.RESET}")
        else:
            log(f"\n  {_C.GREEN}✓ Using provider: {_C.BOLD}{chosen}{_C.RESET}")
        config["default_provider"] = chosen
        save_config(config)
    else:
        log(f"\n  {_C.RED}✗ No working providers found!{_C.RESET}")
        log(f"  {_C.DIM}Use /setkey <key> or configure ~/.agent-nimi/config.json{_C.RESET}")
        # Keep current default so at least the agent can be constructed
        chosen = preferred

    log()
    return chosen, config
