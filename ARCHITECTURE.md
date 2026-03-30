# AgentNimi — Complete Architecture & Technical Reference

> **Last updated:** 2026-03-19
> **Current score:** ~85/100 (up from ~40/100 before the 10-phase improvement plan)
> **Python version:** 3.x | **Framework:** Flask | **Venv:** `.venv`

---

## Table of Contents

1. [What Is AgentNimi?](#1-what-is-agentnimi)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Directory Structure](#3-directory-structure)
4. [Configuration System](#4-configuration-system)
5. [LLM Providers](#5-llm-providers)
6. [Tool System](#6-tool-system)
7. [Core Modules — Detailed](#7-core-modules--detailed)
8. [Web Interface](#8-web-interface)
9. [Data Flow: A Chat Request End-to-End](#9-data-flow-a-chat-request-end-to-end)
10. [The 10-Phase Improvement Plan](#10-the-10-phase-improvement-plan)
11. [Critical Rules & Gotchas](#11-critical-rules--gotchas)
12. [Persistence & File Locations](#12-persistence--file-locations)
13. [Testing Conventions](#13-testing-conventions)
14. [Extending the Agent](#14-extending-the-agent)

---

## 1. What Is AgentNimi?

AgentNimi is an **autonomous AI cybersecurity agent** deployed on Kali Linux with full root access. It assists professional penetration testers with:

- Reconnaissance, scanning, and enumeration
- Vulnerability assessment and exploitation
- Post-exploitation, privilege escalation, lateral movement
- System administration and hardening
- Code writing, debugging, and analysis

It uses **multiple LLM providers** (cloud and local), a **smart routing system** that learns which provider handles which task best, a **tool system** for executing real commands on the host, and **multi-agent orchestration** for complex missions.

The agent runs in two modes:
- **CLI** (`main.py`) — interactive terminal interface
- **Web UI** (`web/server.py`) — Flask app on port 1337 with SSE streaming

---

## 2. High-Level Architecture

```
User Input (CLI or Web)
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  AgentNimi.chat()                                               │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐   │
│  │ Episodic │→ │  Fact    │→ │ Strategy │→ │   Workflow    │   │
│  │ Recall   │  │ Inject   │  │ Memory   │  │  Detection    │   │
│  │ (recall  │  │ (query   │  │ (recom-  │  │  (keyword     │   │
│  │  similar │  │  known   │  │  mend    │  │   matching)   │   │
│  │  past    │  │  facts)  │  │  best    │  │               │   │
│  │  tasks)  │  │          │  │  strat)  │  │               │   │
│  └──────────┘  └──────────┘  └──────────┘  └───────┬───────┘   │
│                                                     │           │
│        ┌────────────────────┬───────────────────────┤           │
│        │                    │                       │           │
│        ▼                    ▼                       ▼           │
│  ┌───────────┐    ┌──────────────┐    ┌──────────────────┐      │
│  │  Direct   │    │ Multi-Agent  │    │    Workflow      │      │
│  │  Agent    │    │ Orchestrator │    │    Pipeline      │      │
│  │  Loop     │    │ (5 roles)    │    │  (step chains)   │      │
│  └─────┬─────┘    └──────┬───────┘    └────────┬─────────┘      │
│        │                 │                     │                │
│        └─────────────────┴─────────────────────┘                │
│                          │                                      │
│                    ┌─────▼──────┐                                │
│                    │ Evaluator  │ → Reflexion retry if low      │
│                    └─────┬──────┘                                │
│                          │                                      │
│                    ┌─────▼──────┐  ┌────────────┐               │
│                    │  Store     │  │  Strategy   │               │
│                    │  Episode   │  │  Record     │               │
│                    └────────────┘  └────────────┘               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Directory Structure

```
agent-nimi/
│
├── main.py                     # CLI entry point (460 lines)
├── config.py                   # Configuration management (309 lines)
├── requirements.txt            # Python dependencies
├── setup.sh                    # Environment setup script
├── IMPROVEMENT_PLAN.md         # 10-phase improvement plan (research → implementation)
├── ARCHITECTURE.md             # THIS FILE
│
├── core/                       # Brain of the agent
│   ├── __init__.py
│   ├── agent.py                # Main AgentNimi class (1088 lines) ★ CENTRAL FILE
│   ├── router.py               # Smart provider routing (500+ lines)
│   ├── evaluator.py            # Auto-evaluation, task classification (500+ lines)
│   ├── memory.py               # Learning memory — EWMA provider scores (165 lines)
│   ├── episodic_memory.py      # Long-term episode storage (400+ lines)
│   ├── fact_memory.py          # Persistent key-value facts (300+ lines)
│   ├── strategy_memory.py      # Meta-learning: which strategy works best (209 lines)
│   ├── world_state.py          # Structured environment model (200+ lines)
│   ├── decomposer.py           # LLM-assisted task decomposition (500+ lines)
│   ├── multiagent.py           # Multi-agent orchestrator (639 lines)
│   ├── workflows.py            # Workflow engine + pre-built pipelines (414 lines)
│   ├── progress.py             # Progress ledger, stall detection (200+ lines)
│   ├── audit.py                # Append-only audit log (54 lines)
│   ├── monitor.py              # System health monitor (213 lines)
│   ├── self_edit.py            # Governed self-editing of config (103 lines)
│   ├── self_model.py           # Agent self-model snapshot (102 lines)
│   └── session_memory.py       # Ephemeral per-session memory (49 lines)
│
├── providers/                  # LLM backend integrations
│   ├── __init__.py             # Provider registry auto-imports (16 lines)
│   ├── base.py                 # Abstract LLMProvider base + registry (54 lines)
│   ├── grok_provider.py        # xAI Grok (grok-3) — cloud (76 lines)
│   ├── copilot_provider.py     # GitHub Copilot CLI — cloud (187 lines)
│   ├── openrouter_provider.py  # OpenRouter (free tier) — cloud (78 lines)
│   └── ollama_provider.py      # Ollama local inference (140 lines)
│
├── tools/                      # Agent tool execution
│   ├── __init__.py             # Tool auto-registration (24 lines)
│   ├── registry.py             # Tool registry + action classification (207 lines)
│   ├── file_pkg_tools.py       # File I/O + apt package management (121 lines)
│   ├── shell_tools.py          # Shell exec + background processes (157 lines)
│   ├── monitoring_tools.py     # System status, processes, network (131 lines)
│   ├── security_tools.py       # nmap, nikto, gobuster, hydra, etc. (96 lines)
│   └── custom_loader.py        # Runtime user-defined custom tools (247 lines)
│
└── web/                        # Flask web interface
    ├── server.py               # App factory, blueprint registration (61 lines)
    ├── blueprints/
    │   ├── chat.py             # /chat route + SSE streaming (222 lines)
    │   ├── conversations.py    # Conversation CRUD
    │   ├── monitor.py          # System monitor routes
    │   ├── providers.py        # Provider management routes
    │   ├── router.py           # Router stats/control routes
    │   ├── system.py           # System info routes
    │   └── tools.py            # Tool listing routes
    ├── services/
    │   ├── agent_service.py    # Agent init/management (78 lines)
    │   └── conversation_service.py
    ├── static/
    │   ├── css/style.css
    │   └── js/app.js
    ├── templates/
    │   └── index.html
    └── utils/
        └── state.py            # Global Flask app state
```

---

## 4. Configuration System

**File:** `config.py` (309 lines)

Configuration is a nested dict stored at `~/.agent-nimi/config.json`. The `DEFAULT_CONFIG` in code defines all keys; user overrides are merged on load.

### Key Sections

| Section | Purpose | Key Fields |
|---------|---------|------------|
| `providers` | LLM backend credentials | `grok.api_key`, `copilot.model`, `ollama.base_url`, etc. |
| `routing` | Smart router behavior | `enabled`, `prefer_cloud`, `auto_learn`, `min_samples_to_trust` |
| `safety` | Tool execution gates | `confirm_destructive`, `confirm_threshold` ("irreversible"/"dangerous"), `confirm_timeout`, `blocked_commands` |
| `multiagent` | Multi-agent orchestration | `enabled_in_agent_mode`, `force_single_agent`, `max_subtasks`, `max_replans`, `roles`, `escalation_chain` |
| `reflexion` | Self-critique retry loop | `max_refinements` (2), `quality_threshold` (0.55), `progress_summary_interval` (5), `stall_window` (4) |
| `memory` | Context & memory limits | `max_context_tokens` (12000), `max_episodes` (500), `max_facts` (1000) |
| `evaluation` | Quality scoring config | `semantic_eval_enabled`, `semantic_eval_threshold`, blend weights |
| `workflow` | Workflow auto-detection | `enabled`, `min_keyword_score` |
| `copilot_budget` | Copilot quota tracking | `monthly_premium_requests`, phase models, usage counters |
| `architecture` | Agent identity & trust | `agent_name`, `agent_version`, trust tiers, mode controller |
| `logging` | Log persistence | `enabled`, `log_dir`, `max_log_size_mb` |
| `monitoring` | System health alerts | `auto_start`, thresholds for CPU/memory/disk |

### Key Functions

- `load_config()` → merged dict (defaults + user overrides)
- `save_config(config)` → persists to `~/.agent-nimi/config.json`
- `get_copilot_budget(config)`, `add_copilot_usage(config, multiplier)`, `get_copilot_remaining(config)`

### SYSTEM_PROMPT

Defined in `config.py`. A ~2KB prompt establishing AgentNimi's identity as an offensive cybersecurity AI with full Kali Linux root access. Lists all capabilities (recon, scanning, exploitation, post-exploitation, etc.) and tool call syntax.

---

## 5. LLM Providers

### Base Class (`providers/base.py`)

```python
class LLMProvider:
    def name(self) -> str: ...
    def chat(self, messages, stream=False) -> str | Generator: ...
    def test_connection(self) -> bool: ...
```

Providers register via `@register_provider("name")` decorator. Retrieved via `get_provider(name, config)`.

### Provider Details

| Provider | Class | API | Default Model | Notes |
|----------|-------|-----|---------------|-------|
| **Grok** | `GrokProvider` | OpenAI-compatible (`api.x.ai`) | `grok-3` | Primary cloud provider for complex reasoning |
| **Copilot** | `CopilotProvider` | GitHub Copilot CLI | `gpt-4.1` | Budget-tracked, phase-based model selection |
| **OpenRouter** | `OpenRouterProvider` | OpenAI-compatible | `llama-3-70b-instruct` | Free tier fallback |
| **Ollama** | `OllamaProvider` | Local HTTP | `llama3` | 4GB VRAM local inference |

### Provider Selection

The **SmartRouter** in `core/router.py` selects providers based on:

1. **Learned scores** — EWMA performance data from past interactions (needs ≥3 samples)
2. **Static task preferences** — 22+ task types mapped to provider priority orders in `TASK_PREFERENCES`
3. **Absolute fallback** — try every configured provider

**⚠️ CRITICAL RULE:** `TASK_PREFERENCES` maps each task type to a specific provider ORDER. Never flatten these to a single global priority. Different tasks need different providers (e.g., `code` → copilot-first, `recon` → ollama-first, `exploit` → grok-first).

---

## 6. Tool System

### Registry (`tools/registry.py`)

Tools are registered via the `@tool` decorator:

```python
@tool(
    name="nmap_scan",
    description="Run nmap scan against a target",
    parameters={"target": "IP/hostname", "flags": "nmap flags"},
    action_class="dangerous",          # Phase 5: safety classification
    capabilities=["scan", "recon"],    # for tool discovery
    provider_affinity="grok",          # preferred provider for this tool
)
def nmap_scan(target, flags="-sV"): ...
```

### Action Classification (Phase 5)

Every tool has an `action_class` in its manifest:

| Class | Level | Meaning | Example tools |
|-------|-------|---------|---------------|
| `read_only` | 0 | No side effects | `file_read`, `system_status`, `searchsploit` |
| `reversible` | 1 | Can be undone | `file_write` (has backup) |
| `irreversible` | 2 | Cannot be undone | `shell_exec`, `bg_process_kill` |
| `dangerous` | 3 | Could cause harm | `nmap_scan`, `nikto_scan`, `hydra_bruteforce` |

When `confirm_destructive: true` in config, tools at or above the `confirm_threshold` level require user confirmation via SSE (web) or auto-approve (CLI).

### Tool Categories

| File | Tools | Action Classes |
|------|-------|----------------|
| `file_pkg_tools.py` | `file_read`, `file_write`, `file_undo`, `pkg_install`, `pkg_remove`, `pkg_search` | read_only, reversible, irreversible |
| `shell_tools.py` | `shell_exec`, `shell_exec_background`, `bg_process_status`, `bg_process_kill` | irreversible, read_only |
| `monitoring_tools.py` | `system_status`, `process_list`, `network_connections`, `service_status`, `log_reader`, `disk_usage` | all read_only |
| `security_tools.py` | `nmap_scan`, `nikto_scan`, `gobuster_scan`, `hydra_bruteforce`, `enum4linux`, `searchsploit` | dangerous (except searchsploit = read_only) |
| `custom_loader.py` | `create_tool`, `delete_tool`, `list_custom_tools` + user-defined | varies |

### Tool Call Format

LLMs output tool calls in this format (parsed by `parse_tool_call()`):

```
TOOL_CALL: tool_name
{"param1": "value1", "param2": "value2"}
```

---

## 7. Core Modules — Detailed

### 7.1 AgentNimi (`core/agent.py` — 1088 lines) ★

The central orchestrator. Everything flows through this class.

**Constructor (`__init__`):**
- Loads config, creates provider, sets up messages list
- Initializes: SmartRouter, EpisodicMemory, FactMemory, StrategyMemory, WorldState
- Sets up safety config, logging, mode controller, steering queue

**`chat(user_input, stream_callback)` — Main entry point:**

```
1. Classify task type
2. Recall episodic memory + inject facts into context
3. Check if target clarification is needed (scan without IP?)
4. Check strategy memory for recommended approach
5. Detect workflows (keyword match or strategy memory)
   → If matched: _chat_workflow()
6. Check if multiagent is appropriate (mission decomposes into >1 subtask)
   → If yes: _chat_multiagent()
7. Smart route to best provider
8. Run _agent_loop() (direct single-agent execution)
9. Reflexion retry: evaluate quality, retry up to 2x if below 0.55
10. Auto-evaluate, learn (update router scores)
11. Store episode in episodic memory
12. Record strategy outcome in strategy memory
13. Manage context window (compress if over token budget)
14. Return response
```

**`_agent_loop(stream_callback, max_iterations=20)` — Tool execution loop:**

```
For each iteration:
  1. Check mode switches and cancellation
  2. Drain steering messages
  3. Call LLM (with graceful degradation on failure)
  4. Parse response for tool call
     - If no tool call → return text response
     - If tool call:
       a. Check workflow tool whitelist (Phase 9)
       b. Safety check (blocked commands)
       c. Confirmation gate (Phase 5) for destructive actions
       d. Execute tool via run_tool()
       e. Log command, update world state
       f. Record in progress ledger
       g. Generate reflection prompt
       h. Emit reasoning trace (Phase 7)
       i. Check for stalls
       j. Periodic progress summary
  5. Loop back for next LLM call
```

**`_call_llm(stream_callback)` — LLM call with graceful degradation:**

If the current provider throws an exception, the router's `degrade()` method transparently switches to the next available provider and retries once. The user is notified via SSE.

**`_chat_multiagent(user_input, stream_callback)`:**

Delegates to `MultiAgentOrchestrator.run_mission()`, then evaluates/learns/stores episode.

**`_chat_workflow(user_input, workflow, task_type, stream_callback)`:**

Runs a workflow pipeline via `run_workflow()`, then evaluates/learns/stores episode + strategy.

**Other key methods:**
- `_needs_target_clarification()` — detects scan requests without a concrete IP/domain
- `_should_use_multiagent()` — decomposes prompt; if >1 subtask, use multiagent
- `_manage_context_window()` — compresses old messages to stay within token budget
- `_needs_confirmation()` / `_request_confirmation()` — destructive action gate
- `_emit_reasoning_trace()` — structured ReAct-style trace to audit + SSE
- `steer()` / `_drain_steer_messages()` — mid-execution operator steering
- `switch_provider()` / `enable_routing()` / `disable_routing()` — provider control

---

### 7.2 SmartRouter (`core/router.py` — 500+ lines)

Routes each prompt to the optimal provider+model.

**`route(prompt)`:**
1. Classify task type via evaluator
2. Check learned memory (EWMA scores) — need ≥3 samples to trust
3. Fall back to `TASK_PREFERENCES` static priority
4. Absolute fallback: try any configured provider

**`degrade(failed_provider, prompt, stream_callback)` (Phase 10.1):**

When a provider fails mid-conversation, skips it and tries the next in the preference chain. Emits `provider_degraded` SSE event.

**`route_subtask(task_type, prompt)`:**

Used by multiagent orchestration where task type is already known.

**`explain_route(prompt)`:**

Returns a human-readable dict explaining why a specific provider was chosen (learned vs static, scores, etc.). Used by reasoning trace.

**`TASK_PREFERENCES` (critical constant):**

Maps 22+ task types to ordered provider lists:
```python
"code":       ["copilot", "grok", "openrouter", "ollama"]
"recon":      ["ollama", "grok", "openrouter"]
"exploit":    ["grok", "openrouter", "ollama"]
"log_triage": ["ollama", "grok", "openrouter"]
# ... etc
```

---

### 7.3 AutoEvaluator (`core/evaluator.py` — 500+ lines)

Scores every LLM response automatically.

**`classify_task(prompt)`** — regex-based task classification into ~20 types

**`evaluate(prompt, response, ...)`** — full evaluation returning:
```python
{
    "quality": float,     # 0-1, higher = better
    "latency": float,     # 0-1, higher = faster
    "cost": float,        # 0-1, higher = cheaper  
    "task_type": str,
    "issues": list[str],  # detected problems
}
```

**Quality scoring heuristics:**
- Bell-curve length scoring (not too short, not too long)
- Hallucination detection (10 marker phrases like "I cannot", "as an AI")
- Task alignment (code task → should have code blocks, scan task → should have tool calls)
- Tool usage bonus (used tools = more useful)
- Failure/error penalty

**`evaluate_semantic(prompt, response)`** (Phase 6):

Optional LLM-as-judge evaluation. Fires when heuristic quality < threshold. Scores on 4 axes (relevance, correctness, completeness, conciseness) and blends 40% heuristic + 60% semantic.

---

### 7.4 Memory Systems

#### LearningMemory (`core/memory.py` — 165 lines)
- **What:** EWMA scores for provider+model performance per task type
- **Used by:** SmartRouter for learned routing decisions
- **Persistence:** `~/.agent-nimi/memory/scores.json` + `history.jsonl`
- **Key:** composite = 0.60×quality + 0.25×latency + 0.15×cost

#### EpisodicMemory (`core/episodic_memory.py` — 400+ lines)
- **What:** Complete interaction episodes (user input, response, quality, tools used, strategy, outcome)
- **Used by:** `chat()` to inject relevant past experience into LLM context
- **Persistence:** `~/.agent-nimi/memory/episodes.jsonl`
- **Recall:** Keyword + task type matching, returns formatted context block
- **Limit:** 500 episodes max

#### FactMemory (`core/fact_memory.py` — 300+ lines)
- **What:** Key-value facts with subject, content, confidence, source
- **Used by:** `chat()` to inject known facts into context
- **Scopes:** Global (persisted to disk) + Engagement (in-memory, per-session)
- **Persistence:** `~/.agent-nimi/memory/facts.json`
- **Limit:** 1000 global facts max

#### StrategyMemory (`core/strategy_memory.py` — 209 lines)
- **What:** EWMA tracking of which execution strategies work best per task type
- **Strategies tracked:** `direct`, `multiagent`, `workflow:<name>`, `reflexion_retry`
- **Also tracks:** Tool frequency per strategy (which tools are most used)
- **Used by:** `chat()` to pre-select the best approach before execution
- **Persistence:** `~/.agent-nimi/memory/strategies.json` + `strategy_history.jsonl`

#### SessionMemory (`core/session_memory.py` — 49 lines)
- **What:** Ephemeral per-conversation state (in-flight operations, raw recon, findings)
- **Not persisted** — lives only for the duration of a session

#### WorldState (`core/world_state.py` — 200+ lines)
- **What:** Structured model of the environment (files observed, hosts scanned, services found, packages installed, env facts)
- **Updated:** After every tool execution via `update_from_tool_result()`
- **Used by:** Progress summaries injected into LLM context
- **Not persisted** — rebuilt each session from tool observations

---

### 7.5 Task Decomposition (`core/decomposer.py` — 500+ lines)

**`decompose_mission(agent, text, max_subtasks)`:**
1. Try LLM-assisted decomposition (asks a cheap provider to break down the mission)
2. Fall back to regex-based splitting (sentence boundaries, bullet points)
3. Returns list of subtask strings

**`decompose_mission_structured(agent, text)`:**
Returns `Subtask` dataclass objects with:
```python
@dataclass
class Subtask:
    index: int
    description: str
    task_type: str
    depends_on: list[int]      # dependency DAG
    recommended_tools: list[str]
    complexity: str             # low/medium/high
```

**`estimate_complexity(agent, text)`** → "low" / "medium" / "high"

**`replan_if_needed(agent, original_plan, execution_results)`:**
Asks LLM if the plan needs adjustment based on execution results. Returns new plan or None.

---

### 7.6 Multi-Agent Orchestrator (`core/multiagent.py` — 639 lines)

**`MultiAgentOrchestrator.run_mission(user_input, stream_callback)`:**

1. Decompose mission into subtasks
2. Select specialist roles based on complexity:
   - **Low:** just executor
   - **Medium:** planner + researcher + executor
   - **High:** all 5 (planner, researcher, executor, critic, memory_curator)
3. Execute subtask-role assignments in parallel (each routed to best provider)
4. Collect results with escalation (if primary provider fails, try escalation chain)
5. Check if replanning is needed (`replan_if_needed()`)
6. **Boss synthesis** — Nimi synthesizes a final answer from all role outputs
7. **Critic review** — separate provider reviews the boss answer on 4 criteria
8. If critic says needs improvement → refine and re-synthesize (up to 2 attempts)

**Roles:**
- `planner` — creates execution plan
- `researcher` — gathers background info
- `executor` — performs the main task
- `critic` — reviews outputs for quality
- `memory_curator` — extracts facts worth remembering

**SSE events:** `boss_approved`, `boss_refinement`, `critic_review`, `multiagent_replan`

---

### 7.7 Workflow Engine (`core/workflows.py` — 414 lines)

**`WorkflowStep`:** prompt template (with `{context}`), optional `tools_allowed` list, optional gate function

**`Workflow`:** named sequence of steps with description and tags

**`run_workflow(agent, workflow, initial_input, stream_callback)`:**

Chains steps sequentially: each step's output becomes the next step's `{context}`. If a gate function returns False, the workflow aborts early.

**Tool whitelist enforcement:** During a workflow step, the agent loop blocks any tool not in `tools_allowed`. An empty list means no tools (analysis only). `None` means all tools allowed.

**Pre-built workflows:**

| Name | Steps | Purpose |
|------|-------|---------|
| `recon` | enumerate → analyze → report | Full reconnaissance pipeline |
| `exploit` | research → develop → validate | Exploit development pipeline |
| `analysis` | gather → analyze → synthesize | Deep analysis pipeline |
| `hardening` | audit → fix → verify | System hardening pipeline |

**`detect_workflow(user_input)`:** Keyword-based auto-detection. Needs ≥2 keyword hits to trigger. Also supports explicit `"run recon workflow on ..."`.

---

### 7.8 Progress & Reflection (`core/progress.py` — 200+ lines)

**`ProgressLedger`:**
- Tracks every tool call with MD5-hashed args for deduplication
- `record_action()` returns True if the action is new (not a repeat)
- `is_stalled(window)` — True if last N actions are all repeats or failures
- `consecutive_failures()` — count of consecutive failed tool calls
- `reflection_prompt()` — generates a metacognitive prompt after each tool execution (e.g., "Was this action useful? What should you try next?")
- `summary(remaining_iterations)` — progress report injected every N iterations

---

### 7.9 Audit (`core/audit.py` — 54 lines)

Append-only JSONL log at `~/.agent-nimi/logs/audit.jsonl`. Fields >5000 chars are truncated.

**`audit_event(event_type, data)`** — logs with timestamp
**`read_audit(n)`** — returns last N events

---

### 7.10 Self-Edit & Self-Model

**`core/self_edit.py`** — Governed config changes with:
- Protected paths (cannot edit `providers.*.api_key`, etc.)
- Rollback on failure
- Audit logging of all changes

**`core/self_model.py`** — Builds a snapshot dict of the agent's identity, capabilities, performance, and conclusion. Used for introspection.

---

## 8. Web Interface

### Server (`web/server.py`)
- Flask app factory pattern
- Runs on port 1337
- Registers blueprints: chat, conversations, monitor, providers, router, system, tools

### Chat Flow (`web/blueprints/chat.py`)
- `POST /chat` with `{ message, conversation_id, mode }`
- Creates SSE stream via `Response(generate(), mimetype='text/event-stream')`
- `stream_callback` receives all events from the agent and formats as SSE

### SSE Events (emitted during execution)

| Event | When | Data |
|-------|------|------|
| `task_classified` | After classifying prompt | `{task_type}` |
| `routed` | After routing to provider | `{provider, model, task_type}` |
| `agent_start` | Agent loop begins | `{provider, max_iterations}` |
| `iteration` | Each loop iteration | `{current, max, provider}` |
| `llm_call_start/done` | LLM call lifecycle | `{provider, elapsed}` |
| `tool_start` | Before tool execution | `{tool, args}` |
| `tool_result` | After tool execution | `{tool, success, output, elapsed}` |
| `safety_check` | Safety validation | `{tool, passed}` |
| `confirm_request` | Destructive action gate | `{tool, args, action_class, timeout}` |
| `confirm_timeout` | User didn't respond | `{tool}` |
| `tool_declined` | User declined | `{tool}` |
| `workflow_tool_blocked` | Tool not in whitelist | `{tool, allowed}` |
| `workflow_start/step/done` | Workflow lifecycle | `{workflow, step, ...}` |
| `workflow_gate_failed` | Gate returned False | `{step}` |
| `reflection` | After reflection prompt | `{iteration, is_new_action, is_stalled}` |
| `reasoning_trace` | ReAct-style trace | `{step, thought, action, observation, reflection}` |
| `stall_detected` | Repeated/failed actions | `{iteration}` |
| `reflexion_retry` | Quality below threshold | `{attempt, quality, issues}` |
| `provider_degraded` | Provider switch | `{from, to, model}` |
| `learning` | After evaluation | `{quality, latency, cost, task_type}` |
| `agent_done` | Agent finished | `{elapsed, tool_calls, tool_successes}` |
| `boss_approved` | Critic approved | `{}` |
| `boss_refinement` | Boss refining | `{attempt}` |
| `critic_review` | Critic reviewing | `{...}` |
| `multiagent_replan` | Plan adjusted | `{...}` |
| `mode_switched` | Mode changed | `{mode}` |
| `steer_ack` | Steering acknowledged | `{message}` |

---

## 9. Data Flow: A Chat Request End-to-End

```
User types: "Run a full recon on 10.0.0.1"
│
├─ Web: POST /chat → chat.py → agent.chat()
│
├─ Classify task: "recon"
├─ Episodic recall: find similar past recon tasks → inject context
├─ Fact inject: any known facts about 10.0.0.1 → inject
├─ Strategy memory: recommend("recon") → "workflow:recon" (if learned)
│
├─ Workflow detected: RECON_WORKFLOW (keyword: "full recon")
│   ├─ Step 1: "enumerate" — tools_allowed: [nmap_scan, shell_exec, file_read]
│   │   └─ Agent loop runs, LLM calls nmap_scan, gets results
│   │   └─ Gate: _not_empty(result) → True, continue
│   ├─ Step 2: "analyze" — tools_allowed: [searchsploit, shell_exec]  
│   │   └─ Agent loop analyzes scan output
│   │   └─ Gate: _not_empty(result) → True, continue
│   └─ Step 3: "report" — tools_allowed: [file_write]
│       └─ Agent loop generates security report
│
├─ Evaluate quality → 0.78 (above 0.55 threshold, no reflexion retry)
├─ Record to learning memory: recon + grok/grok-3 + scores
├─ Record to strategy memory: recon + "workflow:recon" + tools + 0.78
├─ Store episode: full interaction record  
├─ Manage context window: compress if over 12K tokens
│
└─ Return response via SSE stream
```

---

## 10. The 10-Phase Improvement Plan

All 10 phases are **COMPLETE** and tested. See `IMPROVEMENT_PLAN.md` for the original research and specifications.

| Phase | Name | What Was Built | Key Files Modified/Created |
|-------|------|----------------|---------------------------|
| **1** | Self-Reflection & Error Recovery | ProgressLedger, reflection prompts, stall detection, Reflexion retry loop | `core/progress.py` (NEW), `core/agent.py`, `core/evaluator.py`, `config.py` |
| **2** | Structured Memory | EpisodicMemory, FactMemory, context window management | `core/episodic_memory.py` (NEW), `core/fact_memory.py` (NEW), `core/agent.py`, `config.py` |
| **3** | Intelligent Planning | LLM-assisted decomposition, Subtask DAG, complexity estimation, replanning | `core/decomposer.py` (rewritten), `core/multiagent.py`, `config.py` |
| **4** | Multi-Agent Refinement | Iterative boss synthesis, critic review loop, dynamic role selection | `core/multiagent.py` |
| **5** | Safety & Reversibility | Action classification, confirmation gate, file backup/undo | `tools/registry.py`, all tool files, `core/agent.py`, `config.py` |
| **6** | Smarter Evaluation | LLM-as-judge semantic evaluation, blended scoring | `core/evaluator.py`, `config.py` |
| **7** | Observability & Transparency | Reasoning traces (ReAct format), route explanations, richer audit | `core/agent.py`, `core/router.py`, `core/audit.py` |
| **8** | Environment Grounding | Structured world-state model updated from tool results | `core/world_state.py` (NEW), `core/agent.py` |
| **9** | Workflow Patterns | Workflow engine, 4 pre-built pipelines, tool whitelists, auto-detection | `core/workflows.py` (NEW), `core/agent.py`, `config.py` |
| **10** | Graceful Degradation + Strategy Memory | Provider failover, strategy meta-learning (which approach works best) | `core/router.py`, `core/strategy_memory.py` (NEW), `core/agent.py` |

---

## 11. Critical Rules & Gotchas

### ⚠️ Never Flatten TASK_PREFERENCES
The `TASK_PREFERENCES` dict in `core/router.py` maps each task type to a **specific provider order**. Different tasks need different providers. Never replace this with a single global priority list.

### ⚠️ Class Name
The main agent class is `AgentNimi` (not `Agent`). Import as:
```python
from core.agent import AgentNimi
```

### ⚠️ Shell Quoting in Tests
When writing tests, create `.py` files and run them. Don't use `python -c "..."` — shell quoting breaks complex test code.

### ⚠️ Memory Files Are User Data
All files under `~/.agent-nimi/memory/` are learned data. Don't delete them unless specifically testing reset functionality.

### ⚠️ Provider API Keys
Keys are loaded from `~/.agent-nimi/config.json`. The Copilot provider uses the local GitHub CLI auth instead of an API key. Ollama needs no key (local).

### ⚠️ Multiagent Decision Logic
`_should_use_multiagent()` calls `decompose_mission()`. If it returns >1 subtask, multiagent is triggered. This means even simple prompts might go multiagent if the decomposer splits them.

### ⚠️ Workflow vs Multiagent Priority
Workflows are checked **before** multiagent in `chat()`. If a workflow matches, it takes priority.

### ⚠️ Reflexion Retry vs Workflow/Multiagent
The Reflexion retry loop (evaluate → self-critique → retry) only applies to the **direct** agent path. Workflows and multiagent have their own quality mechanisms (critic review for multiagent, gates for workflows).

---

## 12. Persistence & File Locations

All persistent data lives under `~/.agent-nimi/`:

```
~/.agent-nimi/
├── config.json                  # User configuration overrides
├── logs/
│   ├── audit.jsonl              # Audit trail (append-only)
│   └── agent-YYYY-MM-DD.jsonl   # Daily tool execution logs
├── memory/
│   ├── scores.json              # LearningMemory — provider EWMA scores
│   ├── history.jsonl            # LearningMemory — raw evaluation log
│   ├── episodes.jsonl           # EpisodicMemory — interaction episodes
│   ├── facts.json               # FactMemory — persistent facts
│   ├── strategies.json          # StrategyMemory — strategy scores
│   └── strategy_history.jsonl   # StrategyMemory — raw history
├── backups/
│   └── *.bak                    # file_write backups for file_undo
└── custom_tools/
    └── *.json + *.py            # User-created custom tools
```

---

## 13. Testing Conventions

Throughout the 10-phase implementation, tests followed this pattern:

1. Create `test_phaseN.py` in the project root
2. Import modules directly (no pytest framework — just assertions)
3. Track pass/fail counts with `ok(label)` / `fail(label, e)` helpers
4. Print results summary
5. `sys.exit(1)` on any failure
6. **Delete the test file after all tests pass** (`rm test_phaseN.py`)

To run a quick sanity check on a specific module:
```bash
cd /home/nimi/agent-nimi
source .venv/bin/activate
python -c "from core.workflows import list_workflows; print(list_workflows())"
```

---

## 14. Extending the Agent

### Adding a New Provider
1. Create `providers/new_provider.py`
2. Subclass `LLMProvider` and implement `name()`, `chat()`, `test_connection()`
3. Decorate with `@register_provider("new_name")`
4. Add to `providers/__init__.py` imports
5. Add default config in `config.py` under `providers`
6. Add to relevant `TASK_PREFERENCES` entries in `core/router.py`

### Adding a New Tool
1. Add function in appropriate `tools/*.py` file
2. Decorate with `@tool(name=..., description=..., parameters=..., action_class=...)`
3. Tool is auto-registered and available to the LLM

### Adding a New Workflow
1. Define `WorkflowStep` objects and a `Workflow` in `core/workflows.py`
2. Add to `WORKFLOW_REGISTRY`
3. Add keywords to `detect_workflow()` keyword map

### Adding a New Memory Type
1. Create `core/new_memory.py` with load/save/query methods
2. Initialize in `AgentNimi.__init__()`
3. Inject into context in `chat()` method
4. Record after execution completes

---

*This document describes the complete state of AgentNimi as of 2026-03-19, after all 10 improvement phases have been implemented and tested.*
