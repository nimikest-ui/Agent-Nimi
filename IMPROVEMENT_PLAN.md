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
