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
