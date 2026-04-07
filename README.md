# Agent Nimi

An offensive cybersecurity AI agent built for Kali Linux. Agent Nimi orchestrates multiple specialist LLM roles, executes real tools, learns from outcomes, and adapts its approach when blocked.

## Features

- **Multi-agent orchestration** — planner, researcher, executor, critic, and memory curator roles collaborate on complex missions
- **130+ Kali Linux tools** — registered with safety tiers, action classifications, and provider affinity metadata
- **Smart routing** — learns which LLM provider/model performs best for each task type using EWMA scoring
- **Workflow engine** — pre-built pipelines for recon, exploit development, analysis, and system hardening
- **Structured memory** — episodic, fact, strategy, and learning memory systems persist across sessions
- **World state tracking** — maintains a grounded model of discovered hosts, files, and environment state
- **Reflexion loop** — self-critique with stall detection, progress ledgers, and automatic approach pivoting
- **Web UI** — Flask backend with SSE streaming for real-time updates
- **CLI interface** — full-featured REPL with provider switching, router controls, and conversation management

## Requirements

- Python 3.11+
- Kali Linux (recommended) or any Linux distribution
- At least one LLM provider configured:
  - **Grok (xAI)** — requires an API key from [x.ai](https://x.ai)
  - **GitHub Copilot** — requires the Copilot CLI (`npm install -g @github/copilot`)

## Installation

```bash
# Clone the repository
git clone https://github.com/nimikest-ui/Agent-Nimi.git
cd Agent-Nimi

# Run the setup script
chmod +x setup.sh
./setup.sh

# Or install manually
pip install -r requirements.txt
```

## Configuration

On first run, Agent Nimi creates a configuration directory at `~/.agent-nimi/`. Edit the config to add your provider credentials:

```bash
# Start once to generate default config
python main.py

# Edit the config file
nano ~/.agent-nimi/config.json
```

### Provider Setup

**Grok (xAI):**
```json
{
  "providers": {
    "grok": {
      "api_key": "your-xai-api-key",
      "model": "grok-3"
    }
  }
}
```

**GitHub Copilot:**
```bash
npm install -g @github/copilot
copilot login
```

## Usage

### CLI Mode

```bash
python main.py
```

Available commands in the REPL:
- `/help` — show all commands
- `/provider <name>` — switch LLM provider
- `/router on|off|stats` — control smart routing
- `/mode ask|plan|agent` — switch execution mode
- `/reset` — clear conversation history
- `/exit` — quit

### Web UI

```bash
python -m web.server
# Opens at http://localhost:1337
```

## Architecture

Agent Nimi is organized into several layers:

```
main.py                  CLI entry point and REPL
web/                     Flask web server with SSE streaming
├── blueprints/          Route handlers (chat, tools, router, etc.)
├── services/            Business logic (agent, conversations)
└── templates/           HTML templates

core/                    Core agent logic
├── agent.py             Main AgentNimi class
├── mixins/              Responsibility-separated mixins
│   ├── safety.py        Tool safety checks and confirmation gates
│   ├── memory.py        Context window management and persistence
│   ├── mode_control.py  Mode switching and operator steering
│   └── orchestration.py Multiagent and workflow dispatch
├── router.py            Smart provider/model routing
├── evaluator.py         Auto-evaluation with heuristic + semantic scoring
├── workflows.py         Reusable multi-step pipelines
├── decomposer.py        Mission decomposition into typed subtasks
├── progress.py          Progress ledger and stall detection
├── validator.py         Exploit validation and confidence scoring
├── memory.py            Learning memory (EWMA scores)
├── episodic_memory.py   Episode storage
├── fact_memory.py       Fact extraction and storage
├── strategy_memory.py   Strategy outcome tracking
├── world_state.py       Environment state model
└── audit.py             Append-only audit logging

providers/               LLM provider abstraction
├── base.py              Abstract base class and registry
├── grok_provider.py     xAI Grok (OpenAI-compatible API)
└── copilot_provider.py  GitHub Copilot CLI wrapper

tools/                   Tool registry and implementations
├── registry.py          Decorator-based tool registration
├── shell_tools.py       Shell execution tools
├── security_tools.py    Nmap, Nikto, Gobuster, etc.
├── file_pkg_tools.py    File and package management
├── browser_tools.py     Playwright browser automation
├── osint_tools.py       OSINT and reconnaissance
├── monitoring_tools.py  System monitoring
├── memory_tools.py      Memory management tools
└── custom_loader.py     User-defined custom tools
```

For a detailed architecture description, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Persistent Data

All persistent data is stored under `~/.agent-nimi/`:

| Path | Purpose |
|------|---------|
| `config.json` | User configuration |
| `memory/scores.json` | Learned provider/model scores |
| `memory/history.jsonl` | Raw evaluation history |
| `memory/episodes.jsonl` | Episodic memory |
| `memory/facts.json` | Extracted facts |
| `memory/strategies.json` | Strategy outcomes |
| `audit/events.jsonl` | Immutable audit log |
| `logs/` | Daily agent execution logs |
| `custom_tools/` | User-defined tools |

## License

This project is provided as-is for educational and authorized security testing purposes only. Use responsibly and only on systems you have explicit permission to test.
