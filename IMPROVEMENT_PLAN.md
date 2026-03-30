# AgentNimi Improvement Plan

## Methodology

Every module in AgentNimi was audited line-by-line against the 10 principles
distilled from Anthropic, OpenAI (Lilian Weng), Microsoft Magentic-One, LangChain,
and DeepMind research on what makes a good AI agent.

---

## Current-State Scorecard

| # | Research Principle | AgentNimi Today | Score |
|---|---|---|---|
| 1 | **Planning & Decomposition** | `decomposer.py` does regex sentence-splitting + task classification. No dependency graph, no LLM-assisted planning, no replanning mid-execution. | 3/10 |
| 2 | **Memory (Working / Episodic / Semantic)** | `memory.py` stores only EWMA provider performance scores. `session_memory.py` holds raw lists per engagement. No episodic recall of past successes/failures, no semantic fact store. | 2/10 |
| 3 | **Tool Use & Interface** | Strong. `registry.py` has manifests, capability/trust-tier discovery, custom tool creation, balanced-JSON parsing. Good sudo-fallback in `shell_tools.py`. | 7/10 |
| 4 | **Error Recovery & Self-Reflection** | `_agent_loop()` feeds tool errors back to the LLM but has **no** Reflexion-style self-critique, no stall detection, no explicit retry strategy. Loops up to 20 iterations blindly. | 1/10 |
| 5 | **Multi-Agent Architecture** | `multiagent.py` has 5 specialist roles, parallel fan-out, escalation chain. Boss synthesises once. No iterative refinement, no progress ledger, no evaluator-optimizer loop. | 5/10 |
| 6 | **Transparency & Observability** | `audit.py` JSONL trail (truncated 2500 chars). `monitor.py` system health. Web UI shows stats. No reasoning-trace visualisation, no decision explanations. | 4/10 |
| 7 | **Safety & Guardrails** | Trust tiers, protected self-edit paths, safety stripping in shell. No reversibility assessment, no action classification, no human-in-the-loop confirm for destructive ops. | 5/10 |
| 8 | **Learning & Adaptation** | EWMA learning feeds back into routing. `self_edit.py` can modify config. Learning is *performance-only*; no strategy learning, no meta-learning. | 4/10 |
| 9 | **Environment Grounding** | Tools interact with real OS (shell, files, network). But no structured world-state tracking, no observation diffing. | 4/10 |
| 10 | **Start Simple / Composability** | Three modes (ask/plan/agent) is great. But agent loop is monolithic and doesn't compose well with workflows. | 5/10 |

**Aggregate: ~40/100** — strong tool infra and routing, but major gaps in
reflection, memory, planning, and iterative refinement.

---

## Gap Analysis & Improvement Plan

Each improvement is labelled with **impact** (High/Med/Low) and **effort**
(S/M/L/XL). Items are grouped into phases for incremental delivery.

---

### PHASE 1 — Self-Reflection & Error Recovery (Highest Impact)

> *"The single biggest lever for agent quality is letting the agent critique
> its own output before returning it."* — Anthropic

#### 1.1 Inner Self-Reflection Loop  
**Impact: HIGH | Effort: M | File: `core/agent.py`**

**Current:** `_agent_loop()` runs up to 20 iterations. When a tool fails, the
raw error string is appended to `messages` and the LLM is called again with no
guidance on *what went wrong* or *what to try differently*.

**Change:**
After every tool execution (success or failure), inject a **reflection prompt**
before the next LLM call:

```python
# After tool result is obtained in _agent_loop():
reflection_prompt = (
    "REFLECT: The last action was: {action_summary}\n"
    "Result: {truncated_result}\n"
    "Was this successful? What should the next step be? "
    "If the same approach failed before, try a different strategy."
)
messages.append({"role": "user", "content": reflection_prompt})
```

Add a **repetition detector**: track the last N tool calls. If the same
tool+args appears ≥2 times, inject a stronger nudge:

```python
if _is_repeated(tool_history, tool_name, tool_args):
    messages.append({
        "role": "user",
        "content": "WARNING: You have already tried this exact action and it "
                   "failed. You MUST try a different approach or give up on "
                   "this sub-goal and explain why."
    })
```

**Concrete implementation steps:**
1. Add `tool_history: list[dict]` tracking `{"tool", "args", "result_ok", "iteration"}` to `_agent_loop`.
2. After each tool execution, build and inject the reflection prompt.
3. Add `_is_repeated()` helper that checks for duplicate (tool, args) in last 5 entries.
4. Add a `_is_stalled()` check: if 3+ iterations produce no new tool calls AND no final answer, inject a "you appear stuck" nudge.
5. Log reflection events to audit trail.

---

#### 1.2 Outer Evaluator-Optimizer Loop (Reflexion)
**Impact: HIGH | Effort: M | File: `core/agent.py`, `core/evaluator.py`**

**Current:** `chat()` calls `_agent_loop()` once, then `evaluate_and_learn()`.
If the quality score is low, nothing happens — the bad answer is returned anyway.

**Change:**
Wrap the agent loop in an outer retry:

```python
MAX_REFINEMENTS = 2

for attempt in range(1 + MAX_REFINEMENTS):
    answer = self._agent_loop(messages, ...)
    score = self.evaluator.evaluate(task, answer, ...)
    
    if score["quality"] >= 0.7 or attempt == MAX_REFINEMENTS:
        break
    
    # Feed critique back
    messages.append({"role": "assistant", "content": answer})
    messages.append({
        "role": "user",
        "content": f"Your answer scored {score['quality']:.0%} on quality. "
                   f"Issues: {score.get('issues', [])}. Please improve it."
    })
```

**Concrete steps:**
1. Add `issues` list to `_quality_score()` in `evaluator.py` explaining LOW sub-scores (e.g., "response too short", "no code block for code task", "contains error indicators").
2. Add `evaluate_quick()` method that returns quality + issues without the cost/latency scores (those don't make sense for retry decisions).
3. Wrap `_agent_loop()` call in `chat()` with the retry loop.
4. Track `attempt` in audit events.
5. Make `MAX_REFINEMENTS` configurable via `config.py`.

---

#### 1.3 Stall Detection (Magentic-One Style)
**Impact: HIGH | Effort: S | File: `core/agent.py`**

**Current:** The 20-iteration limit is the only safety net against infinite loops.
No awareness of whether *progress* is being made.

**Change:**
Implement a lightweight **Progress Ledger**:

```python
class ProgressLedger:
    def __init__(self):
        self.completed_steps: list[str] = []
        self.current_goal: str = ""
        self.blocked_reasons: list[str] = []
        self.unique_actions: set = set()  # (tool, args_hash)
    
    def record_action(self, tool, args, success):
        key = (tool, hash(json.dumps(args, sort_keys=True)))
        is_new = key not in self.unique_actions
        self.unique_actions.add(key)
        if success:
            self.completed_steps.append(f"{tool}({args})")
        return is_new
    
    def is_stalled(self, window=4) -> bool:
        """True if last `window` actions were all repeats or all failures."""
        ...
```

Inject ledger summary every 5 iterations so the LLM has metacognitive state:

```
"Progress so far: completed {N} unique steps. Current goal: {goal}. 
Blocked on: {reasons}. Remaining iterations: {remaining}."
```

**Concrete steps:**
1. Create `ProgressLedger` class (can live in `core/agent.py` or new `core/progress.py`).
2. Call `ledger.record_action()` after each tool execution.
3. Every 5 iterations, inject a progress summary message.
4. If `ledger.is_stalled()`, trigger the strong nudge from 1.1 or break early.

---

### PHASE 2 — Structured Memory

> *"Without memory, agents are like people with amnesia — they can reason well
> in the moment but cannot improve over time."* — Lilian Weng

#### 2.1 Episodic Memory
**Impact: HIGH | Effort: M | File: new `core/episodic_memory.py`**

**Current:** `memory.py` only stores provider *scores*. The agent forgets
everything about past sessions — what tasks succeeded, what strategies worked,
what tools were useful for what problems.

**Change:**
Create an episodic memory store that records complete interaction *episodes*:

```python
@dataclass
class Episode:
    timestamp: str
    task_summary: str          # 1-line summary of what was asked
    task_type: str             # from evaluator.classify_task()
    strategy_used: str         # "direct" | "multiagent" | "decomposed"
    tools_used: list[str]      # which tools were invoked
    provider_model: str        # which LLM handled it
    outcome: str               # "success" | "partial" | "failure"
    quality_score: float       # from evaluator
    lessons: list[str]         # extracted insights
    context_hash: str          # dedup key
```

Store in `~/.agent-nimi/memory/episodes.jsonl`. At the start of each new task,
retrieve the top-K most relevant past episodes (by task_type + keyword overlap)
and inject them into the system prompt:

```
"Relevant past experience:
- For similar 'code_generation' tasks, using Copilot with shell_exec for testing
  worked well (quality: 0.85)
- Previously failed at 'nmap_scan' when target was unreachable; lesson: always
  ping first"
```

**Concrete steps:**
1. Create `core/episodic_memory.py` with `Episode` dataclass and `EpisodicMemory` class.
2. Implement `store_episode()` and `recall(task_type, keywords, limit=3)`.
3. Use TF-IDF or simple keyword overlap for retrieval (no vector DB needed initially).
4. Call `store_episode()` at the end of `chat()` after evaluation.
5. Call `recall()` at the start of `chat()` and prepend to messages.
6. Add periodic pruning (keep last 500 episodes, summarize older ones).

---

#### 2.2 Semantic Fact Memory
**Impact: MED | Effort: M | File: new `core/fact_memory.py`**

**Current:** Nothing. If the agent learns "the target server runs nginx 1.25"
in one conversation, that fact is lost.

**Change:**
Create a key-value fact store scoped to *engagements* (from `session_memory.py`)
and also a persistent global fact store:

```python
class FactMemory:
    """Stores learned facts as (subject, predicate, value, source, confidence)."""
    
    def store(self, subject, predicate, value, source="agent", confidence=0.8):
        ...
    
    def query(self, subject=None, predicate=None) -> list[Fact]:
        ...
    
    def forget(self, subject, predicate=None):
        ...
```

Facts are extracted by asking the LLM at the end of each interaction:
"List any new facts you learned during this interaction as JSON."

**Concrete steps:**
1. Create `core/fact_memory.py` with `Fact` dataclass and `FactMemory` class.
2. Persist to `~/.agent-nimi/memory/facts.json`.
3. After each `chat()` completion, call a lightweight LLM to extract facts.
4. Inject relevant facts into system prompt for subsequent messages.
5. Integrate with `session_memory.py` for engagement-scoped facts.

---

#### 2.3 Working Memory Management
**Impact: MED | Effort: S | File: `core/agent.py`**

**Current:** The full `messages` list is sent to the LLM every iteration. For
long conversations, this will exceed context windows and/or become expensive.

**Change:**
Implement a sliding-window + summarisation approach:

```python
def _manage_context(self, messages, max_tokens=12000):
    """Keep messages within budget by summarising old turns."""
    total = sum(self._estimate_tokens(m) for m in messages)
    if total <= max_tokens:
        return messages
    
    # Keep system prompt + last N turns + summary of older turns
    system = messages[0]
    recent = messages[-8:]  # last 4 exchanges
    old = messages[1:-8]
    
    summary = self._summarise(old)  # LLM call or heuristic
    return [system, {"role": "system", "content": f"Previous context summary: {summary}"}] + recent
```

**Concrete steps:**
1. Add `_estimate_tokens()` (word_count * 1.3 as rough estimate).
2. Add `_summarise_messages()` that compresses old turns.
3. Call `_manage_context()` before each LLM call in `_agent_loop()`.
4. Make `max_context_tokens` configurable per provider in `config.py`.

---

### PHASE 3 — Intelligent Planning & Decomposition

> *"The gap between demo and production is almost always in planning."*

#### 3.1 LLM-Assisted Decomposition
**Impact: HIGH | Effort: M | File: `core/decomposer.py`**

**Current:** `decompose()` splits on sentence/semicolon boundaries and
classifies each fragment with regex. This produces poor decompositions for
complex, multi-step tasks.

**Change:**
Use the LLM itself to decompose:

```python
DECOMPOSE_PROMPT = """Break this mission into ordered subtasks.
For each subtask return:
- description: what to do
- type: one of {task_types}
- depends_on: list of subtask indices this depends on ([] if independent)
- tools_needed: list of tool names that might help
- estimated_complexity: low/medium/high

Return as JSON array. Mission: {mission}"""

async def decompose(self, mission: str, provider) -> list[Subtask]:
    response = provider.chat([
        {"role": "system", "content": DECOMPOSE_PROMPT.format(
            task_types=list(TASK_PATTERNS.keys()),
            mission=mission
        )}
    ])
    subtasks = json.loads(response)
    return [Subtask(**st) for st in subtasks]
```

**Concrete steps:**
1. Add `Subtask` dataclass with `depends_on: list[int]` field.
2. Replace regex splitting with an LLM call (use cheapest provider for this — Ollama or OpenRouter).
3. Build a dependency DAG from the `depends_on` fields.
4. In multiagent.py, execute independent subtasks in parallel, dependent ones sequentially.
5. Keep regex-based decomposition as fallback if LLM call fails.

---

#### 3.2 Dynamic Replanning
**Impact: HIGH | Effort: M | File: `core/agent.py`, `core/multiagent.py`**

**Current:** Decomposition runs once at the start. If a subtask fails or the
situation changes, there is no replanning.

**Change:**
After each subtask completes (or fails), feed results back to the planner and
ask whether the plan needs adjustment:

```python
REPLAN_PROMPT = """Original plan: {plan}
Completed so far: {completed}
Last result: {last_result}
Should the remaining plan be adjusted? If yes, output the revised remaining subtasks.
If no, output "NO_CHANGE"."""
```

**Concrete steps:**
1. After each subtask in `run_mission()`, call the planner role with `REPLAN_PROMPT`.
2. If response != "NO_CHANGE", replace remaining subtasks.
3. Limit replanning to max 3 times per mission to avoid infinite loops.
4. Log each replan event to audit.

---

### PHASE 4 — Multi-Agent Refinement

#### 4.1 Iterative Boss Synthesis
**Impact: MED | Effort: S | File: `core/multiagent.py`**

**Current:** `_boss_synthesis()` calls the LLM once. If the synthesis is poor
(e.g., misses a worker's critical finding), there's no second chance.

**Change:**
```python
def _boss_synthesis(self, mission, worker_results, provider):
    for attempt in range(2):
        synthesis = self._call_boss(mission, worker_results, provider)
        
        # Have the critic role evaluate the synthesis
        critique = self._call_critic(synthesis, worker_results, provider)
        
        if "APPROVED" in critique:
            return synthesis
        
        # Feed critique back for refinement
        worker_results.append({"role": "critic_review", "content": critique})
    
    return synthesis  # Return best effort after max attempts
```

**Concrete steps:**
1. Extract `_call_boss()` from current `_boss_synthesis()`.
2. Add `_call_critic()` that checks synthesis against worker outputs.
3. Loop up to 2 times.
4. Return final synthesis with confidence indicator.

---

#### 4.2 Dynamic Role Assignment
**Impact: MED | Effort: M | File: `core/multiagent.py`**

**Current:** All 5 roles are always assigned. For simple tasks, this is wasteful.

**Change:**
Let the orchestrator decide which roles are needed:

```python
ROLE_SELECTION_PROMPT = """Given this mission: {mission}
Available roles: planner, researcher, executor, critic, memory_curator
Which roles are needed? Return as JSON list. For simple tasks, fewer roles is better."""

def _select_roles(self, mission_type, complexity):
    if complexity == "low":
        return ["executor"]  # Skip overhead
    elif complexity == "medium":
        return ["planner", "executor", "critic"]
    else:
        return list(self.ROLES.keys())  # All roles
```

**Concrete steps:**
1. Add complexity estimation to decomposer (based on subtask count + types).
2. Add `_select_roles()` method to `MultiAgentOrchestrator`.
3. Only fan out to selected roles.
4. Track role-selection decisions in audit.

---

### PHASE 5 — Safety & Reversibility

> *"Agents should know what they don't know, and be careful with what they
> can't undo."*

#### 5.1 Action Classification & Reversibility Assessment
**Impact: HIGH | Effort: S | File: `core/agent.py`, `tools/registry.py`**

**Current:** Trust tiers exist but are coarse. No distinction between
read-only, reversible-write, and irreversible-destructive actions.

**Change:**
Add an `action_class` to each tool manifest:

```python
ACTION_CLASSES = {
    "read_only":     0,  # file_read, system_status, process_list
    "reversible":    1,  # file_write (can overwrite back), pkg_install (can remove)
    "irreversible":  2,  # shell_exec (arbitrary), pkg_remove, file deletion
    "dangerous":     3,  # nmap, hydra, nikto (legal implications)
}
```

In `_agent_loop()`, before executing an action classified as `irreversible` or
`dangerous`:

```python
if tool_manifest["action_class"] >= 2 and self.confirm_destructive:
    # In web mode: emit SSE event asking for confirmation
    # In CLI mode: prompt user
    confirmed = await self._request_confirmation(tool_name, tool_args)
    if not confirmed:
        messages.append({"role": "user", "content": "User declined this action."})
        continue
```

**Concrete steps:**
1. Add `action_class` field to `default_manifest()` in `registry.py`.
2. Classify all existing tools (see table below).
3. Add confirmation workflow to `_agent_loop()`.
4. Add `confirm_destructive: bool` to config (default True).
5. Support web UI confirmation via SSE.

**Tool Classifications:**

| Tool | Action Class |
|------|------|
| file_read, file_search, system_status, process_list, network_connections, service_status, log_view, bg_process_status | read_only |
| file_write, pkg_install, pkg_update | reversible |
| shell_exec, shell_exec_background, bg_process_kill, pkg_remove | irreversible |
| nmap_scan, nikto_scan, gobuster_scan, searchsploit, hydra_attack, enum4linux | dangerous |

---

#### 5.2 Checkpoint & Rollback for File Operations
**Impact: MED | Effort: S | File: `tools/file_pkg_tools.py`**

**Current:** `file_write` overwrites without backup.

**Change:**
Before writing, save a backup:

```python
def file_write(path, content, append=False):
    if os.path.exists(path) and not append:
        backup_path = path + f".bak.{int(time.time())}"
        shutil.copy2(path, backup_path)
        _recent_backups[path] = backup_path
    ...
```

Add a `file_undo` tool:
```python
@tool("file_undo", "Undo the last write to a file")
def file_undo(path: str) -> str:
    backup = _recent_backups.get(path)
    if backup and os.path.exists(backup):
        shutil.copy2(backup, path)
        return f"Restored {path} from {backup}"
    return "No backup available"
```

---

### PHASE 6 — Smarter Evaluation

#### 6.1 Semantic Quality Evaluation
**Impact: HIGH | Effort: M | File: `core/evaluator.py`**

**Current:** Quality scoring uses heuristics only (length, structure, tool
usage, error keywords). A 2000-word rambling response scores higher than a
precise 50-word correct answer.

**Change:**
Add an LLM-based quality check for important tasks:

```python
EVAL_PROMPT = """Rate this response to the given task.
Task: {task}
Response: {response}
Score 1-10 on: relevance, correctness, completeness, conciseness.
Output JSON: {"relevance": N, "correctness": N, "completeness": N, "conciseness": N, "issues": [...]}"""

def _semantic_quality(self, task, response, provider):
    """Use cheapest LLM as evaluator judge."""
    result = provider.chat([{"role": "user", "content": EVAL_PROMPT.format(...)}])
    scores = json.loads(result)
    return sum(scores[k] for k in ["relevance", "correctness", "completeness", "conciseness"]) / 40
```

**Concrete steps:**
1. Add `_semantic_quality()` to `AutoEvaluator`.
2. Use it only for `quality < 0.5` from heuristics (saves LLM calls).
3. Blend: `final_quality = 0.4 * heuristic + 0.6 * semantic` when semantic is available.
4. Route evaluation calls to the cheapest provider (Ollama or OpenRouter).
5. Make semantic evaluation optional via config.

---

#### 6.2 Richer Heuristic Scoring
**Impact: MED | Effort: S | File: `core/evaluator.py`**

**Current scoring weaknesses:**
- Length bonus is linear (longer = better). Should be bell-curve.
- No penalty for hallucination indicators ("I don't have access to", "as an AI").
- No check for task-response alignment (code task → should contain code).

**Change:**
```python
def _quality_score(self, task_type, response, tool_count):
    issues = []
    
    # Bell-curve length score (peak at ~500 words for general, ~200 for code)
    ideal_length = 500 if task_type not in CODE_TASKS else 200
    length_score = math.exp(-((len(response.split()) - ideal_length) / ideal_length) ** 2)
    
    # Hallucination detector
    HALLUCINATION_MARKERS = ["as an ai", "i cannot access", "i don't have real-time"]
    if any(m in response.lower() for m in HALLUCINATION_MARKERS):
        issues.append("contains_ai_disclaimers")
        length_score *= 0.5
    
    # Task alignment
    if task_type in CODE_TASKS and "```" not in response and "def " not in response:
        issues.append("code_task_missing_code")
        length_score *= 0.7
    
    return length_score, issues
```

---

### PHASE 7 — Observability & Transparency

#### 7.1 Reasoning Trace
**Impact: MED | Effort: S | File: `core/agent.py`, `core/audit.py`**

**Current:** Audit events are opaque and truncated to 2500 chars.

**Change:**
Add structured reasoning events:

```python
def _emit_reasoning_trace(self, step, thought, action, observation, reflection):
    audit.log("reasoning_trace", {
        "step": step,
        "thought": thought[:500],     # What the agent was thinking
        "action": action,              # Tool call or "respond"
        "observation": observation[:500],  # What happened
        "reflection": reflection[:300],    # What the agent concluded
    })
```

Increase audit truncation to 5000 chars (or make configurable). Add a
`/api/reasoning-trace/:conversation_id` endpoint to the web UI.

---

#### 7.2 Decision Explanation
**Impact: MED | Effort: S | File: `core/router.py`**

**Current:** Router picks a provider silently. User/developer can't see *why*.

**Change:**
Add a `explain_route()` method:

```python
def explain_route(self, task_type, history=None):
    """Return human-readable explanation of routing decision."""
    memory_entry = self.memory.best(task_type)
    static_pref = TASK_PREFERENCES.get(task_type, DEFAULT_PRIORITY)
    
    return {
        "task_type": task_type,
        "static_preference": static_pref,
        "learned_best": memory_entry,
        "decision": "learned" if memory_entry else "static",
        "reason": f"Chose {provider} because ..."
    }
```

Emit this as an SSE event in the web UI so users see routing decisions in real-time.

---

### PHASE 8 — Environment Grounding

#### 8.1 World-State Snapshot
**Impact: MED | Effort: M | File: new `core/world_state.py`**

**Current:** The agent has no structured model of what it has observed about the
environment. Each tool call's output is just text thrown into the message history.

**Change:**
Maintain a structured state object:

```python
class WorldState:
    """Tracks observed facts about the execution environment."""
    
    def __init__(self):
        self.files_observed: dict[str, dict] = {}  # path → {size, mtime, snippet}
        self.services_observed: dict[str, str] = {}  # name → status
        self.network_observed: dict[str, dict] = {}  # host:port → {open, service}
        self.packages_installed: set[str] = set()
        
    def update_from_tool_result(self, tool_name, args, result):
        """Parse tool output and update state."""
        if tool_name == "file_read":
            self.files_observed[args["path"]] = {"content_hash": hash(result), ...}
        elif tool_name == "nmap_scan":
            self._parse_nmap(result)
        ...
    
    def diff(self, other: "WorldState") -> dict:
        """What changed between two snapshots."""
        ...
    
    def summary(self) -> str:
        """Concise summary for injection into LLM context."""
        ...
```

Inject `world_state.summary()` every N iterations so the LLM has a structured
view of what it knows about the environment.

---

### PHASE 9 — Configuration & Composability

#### 9.1 Workflow Patterns (Prompt Chaining)
**Impact: MED | Effort: M | File: new `core/workflows.py`**

**Current:** Only mode=agent exists for complex tasks. No way to define
reusable "pipeline" workflows like: scan → analyse → report.

**Change:**
```python
class Workflow:
    """A composable pipeline of agent steps."""
    
    def __init__(self, name, steps):
        self.name = name
        self.steps = steps  # list of {"prompt", "gate", "tools_allowed"}
    
    async def run(self, agent, initial_input):
        context = initial_input
        for step in self.steps:
            result = await agent.chat(
                step["prompt"].format(context=context),
                tools_whitelist=step.get("tools_allowed")
            )
            # Gate: check if we should continue
            if step.get("gate") and not step["gate"](result):
                return {"aborted_at": step, "last_result": result}
            context = result
        return context

# Pre-built workflows
RECON_WORKFLOW = Workflow("recon", [
    {"prompt": "Enumerate subdomains and open ports for {context}", "tools_allowed": ["nmap_scan", "shell_exec"]},
    {"prompt": "Analyze these scan results and identify vulnerabilities:\n{context}", "tools_allowed": []},
    {"prompt": "Write a professional security report based on:\n{context}", "tools_allowed": ["file_write"]},
])
```

---

### PHASE 10 — Hardening & Polish

#### 10.1 Graceful Degradation Chain
**Impact: MED | Effort: S | File: `core/router.py`**

**Current:** If all providers in a task's preference list fail, the agent
returns an error. 

**Change:**
Add a degradation strategy: if the preferred provider fails mid-conversation,
seamlessly switch to the next one and re-attempt, with a note to the user.

---

#### 10.2 Strategy Memory (Meta-Learning)
**Impact: MED | Effort: L | File: `core/memory.py`**

**Current:** Learning is provider-performance only.

**Change:**
Track *which decomposition strategies* work best for *which task types*:

```python
# After successful completion:
strategy_memory.record(
    task_type="security_scan",
    strategy="decompose_then_parallel_multiagent",
    tools_used=["nmap_scan", "nikto_scan"],
    quality=0.9
)

# Before starting a new task:
best_strategy = strategy_memory.best_for("security_scan")
# → "decompose_then_parallel_multiagent"
# → Use this to decide: direct agent, multiagent, or workflow
```

---

## Implementation Priority & Roadmap

| Phase | Items | Impact | Effort | Recommended Order |
|-------|-------|--------|--------|-------------------|
| **1** | Self-Reflection + Reflexion + Stall Detection | 🔴 Critical | M | **Do first** |
| **2** | Episodic + Fact + Working Memory | 🔴 Critical | M-L | **Do second** |
| **3** | LLM Decomposition + Replanning | 🟠 High | M | Third |
| **4** | Iterative Boss + Dynamic Roles | 🟡 Medium | S-M | Fourth |
| **5** | Action Classification + File Rollback | 🟠 High | S | Can parallelize with Phase 3 |
| **6** | Semantic Evaluation + Better Heuristics | 🟠 High | M | After Phase 1 (Reflexion needs it) |
| **7** | Reasoning Trace + Decision Explanation | 🟡 Medium | S | After Phase 1 |
| **8** | World-State Tracking | 🟡 Medium | M | After Phase 2 |
| **9** | Workflow Patterns | 🟡 Medium | M | After Phases 1-3 stable |
| **10** | Degradation + Meta-Learning | 🟢 Nice-to-have | M-L | Last |

**Estimated total effort:** ~4-6 weeks of focused development for all phases.
Phase 1 alone (the highest-impact items) could be done in **3-5 days**.

---

## Quick Wins (Can Do Today)

These are small changes (< 30 min each) with immediate impact:

1. **Repetition detector** in `_agent_loop()` — just track last 5 tool calls and warn on duplicates
2. **Better hallucination detection** in `evaluator.py` — add the marker list
3. **Increase audit truncation** from 2500 → 5000 chars
4. **Add `action_class` to existing tool manifests** — just metadata, no behavior change yet
5. **Bell-curve length scoring** in `_quality_score()` instead of linear
6. **Log routing decisions** with task_type and chosen provider to audit trail

---

## Architecture Diagram (After All Phases)

```
User Input
    │
    ▼
┌─────────────────────────────────────────────┐
│  Agent.chat()                                │
│  ┌───────────┐  ┌──────────┐  ┌───────────┐ │
│  │ Episodic  │  │  Fact    │  │  Working  │ │
│  │ Recall    │→ │ Inject   │→ │ Memory    │ │
│  │ (Phase 2) │  │ (Phase 2)│  │ Mgmt (2.3)│ │
│  └───────────┘  └──────────┘  └───────────┘ │
│        │                                     │
│        ▼                                     │
│  ┌─────────────────────┐                     │
│  │ LLM Decomposer      │ ← Replanning (3.2) │
│  │ (Phase 3.1)          │                     │
│  └──────────┬──────────┘                     │
│             │                                │
│  ┌──────────▼──────────┐                     │
│  │ Smart Router         │ ← explain_route()   │
│  │ + Task Preferences   │   (Phase 7.2)       │
│  └──────────┬──────────┘                     │
│             │                                │
│  ┌──────────▼───────────────────────────┐    │
│  │ Agent Loop (Outer: Reflexion 1.2)    │    │
│  │  ┌────────────────────────────────┐  │    │
│  │  │ Inner Loop (max 20 iterations) │  │    │
│  │  │  ┌──────────┐                  │  │    │
│  │  │  │ LLM Call │                  │  │    │
│  │  │  └────┬─────┘                  │  │    │
│  │  │       ▼                        │  │    │
│  │  │  ┌──────────┐  ┌───────────┐   │  │    │
│  │  │  │Tool Exec │→ │Reflection │   │  │    │
│  │  │  │+ Confirm │  │(Phase 1.1)│   │  │    │
│  │  │  │(Phase 5) │  └───────────┘   │  │    │
│  │  │  └──────────┘       │          │  │    │
│  │  │       ▼             ▼          │  │    │
│  │  │  ┌──────────┐  ┌──────────┐   │  │    │
│  │  │  │ World    │  │ Progress │   │  │    │
│  │  │  │ State    │  │ Ledger   │   │  │    │
│  │  │  │(Phase 8) │  │(Phase 1.3)  │  │    │
│  │  │  └──────────┘  └──────────┘   │  │    │
│  │  └────────────────────────────────┘  │    │
│  │          │                           │    │
│  │  ┌───────▼────────┐                  │    │
│  │  │ Evaluator      │    ◄── Semantic  │    │
│  │  │ (Phase 6)      │        Quality   │    │
│  │  └───────┬────────┘                  │    │
│  │          │ score < 0.7?              │    │
│  │          └──── retry ────────────────┘    │
│  └───────────────────────────────────────┘   │
│        │                                     │
│  ┌─────▼──────┐  ┌────────────┐              │
│  │ Store      │  │  Audit     │              │
│  │ Episode    │  │  + Trace   │              │
│  │ (Phase 2.1)│  │  (Phase 7) │              │
│  └────────────┘  └────────────┘              │
└─────────────────────────────────────────────┘
```

---

*Generated from deep audit of all AgentNimi source files (2,600+ lines of core
code) mapped against research from Anthropic, OpenAI, Microsoft, LangChain, and
DeepMind.*
