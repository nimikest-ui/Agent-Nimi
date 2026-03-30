#!/usr/bin/env python3
"""
AgentNimi - AI-powered Kali Linux agent with root access
Interactive CLI interface
"""
import sys
import os
import readline
import json

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config, save_config
from core.agent import AgentNimi
from core.monitor import SystemMonitor
from core.provider_check import startup_check
from providers import list_providers

# ANSI colors
class C:
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

BANNER = f"""
{C.RED}{C.BOLD}
    ╔═══════════════════════════════════════════════════╗
    ║              {C.CYAN}A G E N T - N I M I{C.RED}                 ║
    ║   {C.WHITE}Offensive Security • Bug Bounty • Exploit{C.RED}     ║
    ╚═══════════════════════════════════════════════════╝{C.RESET}
{C.DIM}  Recon • Enumerate • Exploit • Post-Exploit • Root{C.RESET}
"""

HELP_TEXT = f"""
{C.CYAN}{C.BOLD}Commands:{C.RESET}
  {C.YELLOW}/help{C.RESET}              Show this help
    {C.YELLOW}/provider <name>{C.RESET}   Switch LLM provider (grok, copilot)
  {C.YELLOW}/providers{C.RESET}         List available providers
  {C.YELLOW}/model <name>{C.RESET}      Change model for current provider
  {C.YELLOW}/status{C.RESET}            Show agent & provider status
  {C.YELLOW}/monitor start{C.RESET}     Start background system monitor
  {C.YELLOW}/monitor stop{C.RESET}      Stop background system monitor
  {C.YELLOW}/monitor alerts{C.RESET}    Show recent monitor alerts
  {C.YELLOW}/router status{C.RESET}     Show smart router status & current routing
  {C.YELLOW}/router enable{C.RESET}     Enable smart routing
  {C.YELLOW}/router disable{C.RESET}    Disable smart routing (use manual provider)
  {C.YELLOW}/router stats{C.RESET}      Show learned scores per task type
  {C.YELLOW}/router reset{C.RESET}      Wipe all learned routing data
  {C.YELLOW}/config{C.RESET}            Show current configuration
  {C.YELLOW}/setkey <key>{C.RESET}      Set API key for current provider
  {C.YELLOW}/history{C.RESET}           Show conversation summary
  {C.YELLOW}/clear{C.RESET}             Clear conversation history
  {C.YELLOW}/tools{C.RESET}             List available tools
  {C.YELLOW}/exit{C.RESET}              Exit agent

{C.CYAN}{C.BOLD}Usage:{C.RESET}
  Just type naturally! Examples:
  • "scan 192.168.1.1 — full recon and exploit check"
  • "find vulns on that web app at http://target.com"
  • "enumerate SMB shares on 10.0.0.0/24"
  • "crack these hashes: <paste>"
  • "find all SUID privesc vectors"
  • "write a reverse shell payload for linux x64"
"""


def stream_print(data):
    """Callback to print streaming output - handles both text and structured events."""
    if isinstance(data, dict):
        event = data.get("event", "")

        if event == "task_classified":
            task = data.get("task_type", "general")
            print(f"\n{C.DIM}  ┌─ Task: {C.YELLOW}{task}{C.DIM} ──────────────────────────────────{C.RESET}")

        elif event == "routed":
            prov = data.get("provider", "?")
            model = data.get("model", "?")
            task = data.get("task_type", "")
            print(f"{C.DIM}  │ {C.MAGENTA}⇢ Routed to {C.BOLD}{prov}{C.RESET}{C.MAGENTA}:{model}{C.RESET}")

        elif event == "agent_start":
            prov = data.get("provider", "?")
            print(f"{C.DIM}  │ Provider: {C.WHITE}{prov}{C.RESET}")

        elif event == "iteration":
            cur = data.get("current", 0)
            mx = data.get("max", 20)
            if cur > 1:
                # Only show iteration counter after the first one
                print(f"\n{C.DIM}  ├─ Iteration {C.WHITE}{cur}{C.DIM}/{mx} ─────────────────────────{C.RESET}")

        elif event == "llm_call_start":
            prov = data.get("provider", "?")
            print(f"{C.DIM}  │ 🧠 Thinking ({prov})...{C.RESET}", end="", flush=True)

        elif event == "llm_call_done":
            elapsed = data.get("elapsed", 0)
            length = data.get("response_length", 0)
            print(f"\r{C.DIM}  │ 🧠 LLM responded in {C.WHITE}{elapsed}s{C.DIM} ({length:,} chars){C.RESET}")

        elif event == "safety_check":
            tool = data.get("tool", "?")
            passed = data.get("passed", False)
            if passed:
                print(f"{C.DIM}  │ 🛡️  Safety: {C.GREEN}passed{C.DIM} ({tool}){C.RESET}")
            else:
                print(f"{C.DIM}  │ 🛡️  Safety: {C.RED}BLOCKED{C.DIM} ({tool}){C.RESET}")

        elif event == "tool_start":
            tool = data.get("tool", "")
            args = data.get("args", {})
            # Show a compact summary of args
            arg_parts = []
            for k, v in args.items():
                sv = str(v)
                if len(sv) > 60:
                    sv = sv[:57] + "..."
                arg_parts.append(f"{k}={sv}")
            arg_str = ", ".join(arg_parts) if arg_parts else ""
            print(f"\n{C.CYAN}  │ 🔧 Executing: {C.BOLD}{tool}{C.RESET}{C.DIM}({arg_str}){C.RESET}")

        elif event == "tool_result":
            success = data.get("success", False)
            output = data.get("output", "")
            elapsed = data.get("elapsed", 0)
            out_len = data.get("output_length", len(output))
            icon = f"{C.GREEN}✅" if success else f"{C.RED}❌"
            timing = f"{C.DIM} [{elapsed}s, {out_len:,} chars]{C.RESET}"
            print(f"{icon} Result:{timing}{C.RESET}\n{output}")

        elif event == "tool_blocked":
            print(f"\n{C.RED}  │ ⛔ {data.get('message', 'Blocked')}{C.RESET}")

        elif event == "steer_ack":
            msg = data.get("message", "")
            print(f"\n{C.YELLOW}  │ ▶ Steering: {msg}{C.RESET}")

        elif event == "learning":
            q = data.get("quality", 0)
            l = data.get("latency", 0)
            c = data.get("cost", 0)
            tt = data.get("task_type", "?")
            # Visual quality bar
            bar_len = int(q * 15)
            bar = f"{C.GREEN}{'█' * bar_len}{C.DIM}{'░' * (15 - bar_len)}{C.RESET}"
            print(f"{C.DIM}  │ 📊 Score: {bar} q={q:.2f} lat={l:.2f} cost={c:.2f} ({tt}){C.RESET}")

        elif event == "agent_done":
            elapsed = data.get("elapsed", 0)
            tools = data.get("tool_calls", 0)
            successes = data.get("tool_successes", 0)
            resp_len = data.get("response_length", 0)
            parts = [f"{elapsed}s"]
            if tools > 0:
                parts.append(f"{successes}/{tools} tools ok")
            parts.append(f"{resp_len:,} chars")
            print(f"{C.DIM}  └─ Done: {' · '.join(parts)} ────────────────{C.RESET}")

    else:
        sys.stdout.write(str(data))
        sys.stdout.flush()


def main():
    config = load_config()
    agent = None
    monitor = SystemMonitor(config)

    print(BANNER)

    # Run startup provider health check (interactive key prompting)
    default_provider, config = startup_check(config, interactive=True)

    try:
        agent = AgentNimi(default_provider, config)
        print(f"  {C.GREEN}✓{C.RESET} Provider: {C.BOLD}{agent.provider.name()}{C.RESET}")
    except Exception as e:
        print(f"  {C.RED}✗{C.RESET} Failed to init provider '{default_provider}': {e}")
        print(f"  {C.DIM}Use /provider <name> to switch or /setkey <key> to configure{C.RESET}")
        agent = AgentNimi("grok", config)

    # Auto-start monitor if configured
    if config.get("monitoring", {}).get("auto_start", False):
        monitor.start()
        monitor.on_alert(lambda a: print(f"\n{C.RED}🚨 ALERT: {a['message']}{C.RESET}"))
        print(f"  {C.GREEN}✓{C.RESET} System monitor: {C.GREEN}Running{C.RESET}")

    print(f"\n  {C.DIM}Type /help for commands or just ask me anything.{C.RESET}\n")

    # Setup readline history
    history_file = os.path.expanduser("~/.agent-nimi/history")
    os.makedirs(os.path.dirname(history_file), exist_ok=True)
    try:
        readline.read_history_file(history_file)
    except FileNotFoundError:
        pass
    readline.set_history_length(1000)

    # REPL
    while True:
        try:
            user_input = input(f"{C.RED}agent-nimi{C.RESET}{C.BOLD} ❯ {C.RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{C.DIM}Goodbye.{C.RESET}")
            break

        if not user_input:
            continue

        # Save history
        try:
            readline.write_history_file(history_file)
        except Exception:
            pass

        # Handle commands
        if user_input.startswith("/"):
            handle_command(user_input, agent, monitor, config)
            continue

        # Send to agent
        if not agent:
            print(f"{C.RED}No active provider. Use /provider <name> to configure.{C.RESET}")
            continue

        print(f"\n{C.CYAN}", end="")
        try:
            response = agent.chat(user_input, stream_callback=stream_print)
        except KeyboardInterrupt:
            print(f"\n{C.YELLOW}[Interrupted]{C.RESET}")
            continue
        except Exception as e:
            print(f"\n{C.RED}Error: {e}{C.RESET}")
            continue
        print(f"{C.RESET}\n")

    # Cleanup
    monitor.stop()


def handle_command(cmd: str, agent: AgentNimi, monitor: SystemMonitor, config: dict):
    """Handle slash commands."""
    parts = cmd.split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if command == "/help":
        print(HELP_TEXT)

    elif command == "/exit" or command == "/quit":
        monitor.stop()
        print(f"{C.DIM}Goodbye.{C.RESET}")
        sys.exit(0)

    elif command == "/providers":
        print(f"\n{C.CYAN}Available providers:{C.RESET}")
        for p in list_providers():
            pconf = config["providers"].get(p, {})
            model = pconf.get("model", "?")
            has_key = "✓" if pconf.get("api_key") else ("n/a" if p == "copilot" else "✗")
            current = " ← current" if agent and p in agent.provider.name().lower() else ""
            print(f"  {C.YELLOW}{p}{C.RESET}: model={model}, key={has_key}{C.GREEN}{current}{C.RESET}")
        print()

    elif command == "/provider":
        if not arg:
            print(f"{C.YELLOW}Usage: /provider <name>{C.RESET}")
            return
        try:
            agent.switch_provider(arg)
            config["default_provider"] = arg
            save_config(config)
            print(f"{C.GREEN}Switched to: {agent.provider.name()}{C.RESET}")
            connected = agent.provider.test_connection()
            status = f"{C.GREEN}OK{C.RESET}" if connected else f"{C.YELLOW}Failed{C.RESET}"
            print(f"Connection: {status}")
        except Exception as e:
            print(f"{C.RED}Error: {e}{C.RESET}")

    elif command == "/model":
        if not arg:
            print(f"{C.YELLOW}Usage: /model <model_name>{C.RESET}")
            return
        pname = config.get("default_provider", "grok")
        config["providers"][pname]["model"] = arg
        save_config(config)
        agent.switch_provider(pname)
        print(f"{C.GREEN}Model set to: {arg}{C.RESET}")

    elif command == "/setkey":
        if not arg:
            print(f"{C.YELLOW}Usage: /setkey <api_key>{C.RESET}")
            return
        pname = config.get("default_provider", "grok")
        config["providers"][pname]["api_key"] = arg
        save_config(config)
        agent.switch_provider(pname)
        print(f"{C.GREEN}API key set for {pname}. Testing...{C.RESET}")
        connected = agent.provider.test_connection()
        status = f"{C.GREEN}OK{C.RESET}" if connected else f"{C.YELLOW}Failed{C.RESET}"
        print(f"Connection: {status}")

    elif command == "/status":
        if agent:
            print(f"\n{C.CYAN}Agent Status:{C.RESET}")
            print(f"  Provider: {agent.provider.name()}")
            connected = agent.provider.test_connection()
            status = f"{C.GREEN}Connected{C.RESET}" if connected else f"{C.RED}Disconnected{C.RESET}"
            print(f"  Connection: {status}")
            print(f"  {agent.get_history_summary()}")
            print(f"  Monitor: {'Running' if monitor.is_running else 'Stopped'}")
            print(f"  Alerts: {len(monitor.alert_log)}")
        print()

    elif command == "/monitor":
        if arg == "start":
            if monitor.is_running:
                print(f"{C.YELLOW}Monitor already running{C.RESET}")
            else:
                monitor.on_alert(lambda a: print(f"\n{C.RED}🚨 ALERT: {a['message']}{C.RESET}"))
                monitor.start()
                print(f"{C.GREEN}System monitor started (interval: {monitor.interval}s){C.RESET}")
        elif arg == "stop":
            monitor.stop()
            print(f"{C.YELLOW}System monitor stopped{C.RESET}")
        elif arg == "alerts":
            alerts = monitor.get_alerts()
            if not alerts:
                print(f"{C.DIM}No alerts.{C.RESET}")
            else:
                for a in alerts:
                    print(f"  {C.RED}[{a['timestamp']}] {a['type']}: {a['message']}{C.RESET}")
        else:
            print(f"{C.YELLOW}Usage: /monitor start|stop|alerts{C.RESET}")

    elif command == "/config":
        display_config = json.loads(json.dumps(config))
        # Mask API keys
        for p in display_config.get("providers", {}):
            key = display_config["providers"][p].get("api_key", "")
            if key:
                display_config["providers"][p]["api_key"] = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
        print(f"\n{C.CYAN}Configuration:{C.RESET}")
        print(json.dumps(display_config, indent=2))
        print()

    elif command == "/history":
        if agent:
            print(f"\n{C.CYAN}{agent.get_history_summary()}{C.RESET}\n")

    elif command == "/clear":
        if agent:
            agent.reset_conversation()
            print(f"{C.GREEN}Conversation cleared.{C.RESET}")

    elif command == "/tools":
        from tools import list_tools, get_tool
        from tools.registry import _TOOLS
        print(f"\n{C.CYAN}Available Tools ({len(_TOOLS)}):{C.RESET}")
        for name, info in _TOOLS.items():
            print(f"  {C.YELLOW}{name}{C.RESET}: {info['description']}")
        print()

    elif command == "/router":
        _handle_router_command(arg, agent)

    else:
        print(f"{C.YELLOW}Unknown command. Type /help for available commands.{C.RESET}")


def _handle_router_command(arg: str, agent: AgentNimi):
    """Handle /router subcommands."""
    import json as _json
    sub = arg.strip().lower() if arg else "status"

    if agent is None:
        print(f"{C.RED}No active agent.{C.RESET}")
        return

    if sub == "status":
        if agent.router is None:
            print(f"\n{C.YELLOW}Smart routing is disabled in config (routing.enabled = false).{C.RESET}\n")
            return
        active_str = f"{C.GREEN}active{C.RESET}" if agent.routing_active else f"{C.YELLOW}paused (manual provider override){C.RESET}"
        enabled_str = f"{C.GREEN}enabled{C.RESET}" if agent.router.enabled else f"{C.RED}disabled{C.RESET}"
        print(f"\n{C.CYAN}Smart Router:{C.RESET}")
        print(f"  State:    {enabled_str}")
        print(f"  Routing:  {active_str}")
        print(f"  Current:  {agent.router.name()}")
        stats = agent.router_stats() or {}
        score_count = sum(len(v) for v in stats.get("scores", {}).values())
        hist_count = len(stats.get("history", []))
        print(f"  Learned:  {score_count} provider/model entries across {len(stats.get('scores', {}))} task types")
        print(f"  History:  {hist_count} evaluations recorded\n")

    elif sub == "enable":
        agent.enable_routing()
        print(f"{C.GREEN}Smart routing enabled.{C.RESET}")

    elif sub == "disable":
        agent.disable_routing()
        print(f"{C.YELLOW}Smart routing disabled — manual provider ({agent.provider.name()}) will be used.{C.RESET}")

    elif sub == "stats":
        stats = agent.router_stats()
        if stats is None:
            print(f"{C.YELLOW}Smart routing is disabled.{C.RESET}")
            return
        scores = stats.get("scores", {})
        if not scores:
            print(f"{C.DIM}No learned data yet. Stats will appear after a few interactions.{C.RESET}")
            return
        print(f"\n{C.CYAN}Learned routing scores (composite = 60% quality + 25% latency + 15% cost):{C.RESET}")
        for task_type, providers in sorted(scores.items()):
            print(f"  {C.YELLOW}{task_type}{C.RESET}:")
            # Sort by composite score descending
            sorted_provs = sorted(providers.items(), key=lambda kv: kv[1]["composite"], reverse=True)
            for key, val in sorted_provs:
                bar_len = int(val["composite"] * 20)
                bar = f"{C.GREEN}{'█' * bar_len}{C.DIM}{'░' * (20 - bar_len)}{C.RESET}"
                print(f"    {key:<35} {bar} {val['composite']:.3f}  (n={val['n']})")
        print()

    elif sub == "reset":
        if agent.router and agent.router.memory:
            agent.router.memory.reset()
            print(f"{C.GREEN}Learned routing data wiped.{C.RESET}")
        else:
            print(f"{C.YELLOW}No router memory to reset.{C.RESET}")

    else:
        print(f"{C.YELLOW}Usage: /router status|enable|disable|stats|reset{C.RESET}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AgentNimi - AI Kali Linux Agent")
    parser.add_argument("--web", action="store_true", help="Launch web UI instead of CLI")
    parser.add_argument("--host", default="0.0.0.0", help="Web UI host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=1337, help="Web UI port (default: 1337)")
    args = parser.parse_args()

    if args.web:
        from web.server import run_web
        run_web(host=args.host, port=args.port)
    else:
        main()
