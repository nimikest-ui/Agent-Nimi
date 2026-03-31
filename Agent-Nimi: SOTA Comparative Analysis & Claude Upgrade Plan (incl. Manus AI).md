# Agent-Nimi: SOTA Comparative Analysis & Claude Upgrade Plan (incl. Manus AI)

This document provides a feature-by-feature comparison of Agent-Nimi against leading AI agent frameworks of 2026 (Manus AI, Microsoft Magentic-One, PentAGI, MAPTA), followed by a detailed, file-level implementation plan for upgrading Agent-Nimi to the current state-of-the-art.

![Agent-Nimi vs. Leading AI Agent Projects](https://private-us-east-1.manuscdn.com/sessionFile/Dli0kJSh4HFPbX00KgdXFu/sandbox/FZ3ADZgWiVZfJkY7VjxHSz-images_1775406681742_na1fn_L2hvbWUvdWJ1bnR1L3JhZGFyX2NvbXBhcmlzb25fdjI.png?Policy=eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6Ly9wcml2YXRlLXVzLWVhc3QtMS5tYW51c2Nkbi5jb20vc2Vzc2lvbkZpbGUvRGxpMGtKU2g0SEZQYlgwMEtnZFhGdS9zYW5kYm94L0ZaM0FEWmdXaVZaZkprWTdWanhIU3otaW1hZ2VzXzE3NzU0MDY2ODE3NDJfbmExZm5fTDJodmJXVXZkV0oxYm5SMUwzSmhaR0Z5WDJOdmJYQmhjbWx6YjI1ZmRqSS5wbmciLCJDb25kaXRpb24iOnsiRGF0ZUxlc3NUaGFuIjp7IkFXUzpFcG9jaFRpbWUiOjE3OTg3NjE2MDB9fX1dfQ__&Key-Pair-Id=K2HSFNDJXOU9YS&Signature=XxpUaXKJMk6q0cXo20LGNqdo1JLTXJjDqQhe-UAemiMN1MLn98gNzNL-8GJ6d9ulG7HUmUVHTq5B4gvtXt9fpMC8qpBQnzbjhSz90bNsyjOW8z-mZ2gTywwmzgGyqqU6-E-T82TU41nXyvW13zQzSeTNGqdb8ZKY28GugyNgk1GRljaqfI8b~nqPjVKrWxd8hUZ1Ixaxs7CaKaSIWDGuUeB2bFFliQVyap9LEoNf9TBexh1OH8Z5MftlOCvGJ9CAyCcOhU3xa37BK6Xi9KLEnnYluCe-sqmMBlWx-OXm6gdViHGmH4hrBqxYMsVbjezLii9ARJZmEr33v393~Se1SQ__)

---

## 1. Feature-by-Feature Comparison Matrix

| Feature | Agent-Nimi | Manus AI [1] [2] | Microsoft Magentic-One [3] | PentAGI [4] | MAPTA [5] | Strategic Gap |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Multi-Agent Orchestration** | Fixed 5 roles (`multiagent.py`) | Planner + Execution + Verification | Dynamic Orchestrator + 4 specialists | 13+ specialized roles | Coordinator + Sandbox + Validation | **Moderate**: Agent-Nimi lacks dynamic sub-agent spawning and dedicated verification agents. |
| **Browser & Vision** | None (Text/CLI only) | Full Chromium + visual Set-of-Marks | WebSurfer (Accessibility Tree + Set-of-Marks) | Built-in web scraper | Headless browser integration | **High**: Agent-Nimi is blind to web GUIs and visual context. |
| **Execution Environment** | Direct Kali execution | Isolated E2B cloud VM per task | Local shell / Docker | Isolated Docker per task | Shared per-job Docker | **Moderate**: Agent-Nimi needs better sandboxing for untrusted exploit execution. |
| **Memory & State** | Episodic + Fact KV (`fact_memory.py`) | File system as persistent context | Task Ledger + Progress Ledger | Neo4j Knowledge Graph | Short-term context | **High**: Agent-Nimi's `world_state.py` is flat; needs graph-based tracking or file-system context offloading. |
| **Self-Correction** | Reflexion (post-hoc, max 2) | Verification Agent triggers re-planning | Outer loop replanning | Mentor/Adviser intervention | Proof-of-Exploit Oracle | **High**: Agent-Nimi needs proactive "Think-Before-Act" critique and exploit validation. |
| **Search Integration** | None (relies on local tools) | Wide Research + 7 search types | WebSurfer search | 7+ Search Engines (Tavily, etc.) | Web search | **Moderate**: Agent-Nimi cannot dynamically research new CVEs online. |
| **Tool Management** | Static whitelists | Context-aware logit masking | Dynamic tool assignment | Strict role-based visibility | Role-based assignment | **Moderate**: Agent-Nimi uses rigid whitelists instead of dynamic masking. |

---

## 2. Claude-Ready Implementation Plan

This section outlines the specific architectural changes required to upgrade Agent-Nimi. Provide this plan to Claude for implementation.

### Phase 11: Multimodal Vision & Browser Integration (High Priority)
**Goal:** Enable Agent-Nimi to interact with web applications visually, closing the gap with Manus AI and Magentic-One.

**Implementation Steps:**
1.  **Create `tools/browser_tools.py`**:
    *   Implement a headless browser tool using Playwright or Selenium.
    *   Add functions: `browser_navigate(url)`, `browser_screenshot(element_id)`, `browser_click(element_id)`, `browser_type(element_id, text)`.
    *   Implement a "Set-of-Marks" function that annotates screenshots with numbered bounding boxes over interactive elements.
2.  **Update `providers/base.py` & `providers/grok_provider.py`**:
    *   Add support for multimodal inputs (passing base64 images to `grok-vision-beta` or `gpt-4o`).
3.  **Update `core/agent.py`**:
    *   When a browser tool returns a screenshot, inject the image into the message history for the next LLM call.

### Phase 12: Context Engineering & State Management (High Priority)
**Goal:** Upgrade memory management from flat dictionaries to a hybrid approach using Knowledge Graphs (like PentAGI) and File System Context (like Manus AI).

**Implementation Steps:**
1.  **Refactor `core/world_state.py`**:
    *   Introduce a lightweight graph structure (e.g., using `networkx` or a simple node/edge dictionary).
    *   Nodes: `Host`, `Port`, `Service`, `User`, `File`, `Vulnerability`.
    *   Edges: `HAS_PORT`, `RUNS_SERVICE`, `OWNED_BY`, `CONTAINS_VULN`.
2.  **Implement File-System Context Offloading**:
    *   Instead of keeping all tool outputs in the LLM message history (which blows up the KV-cache), write large outputs to local files and only keep the file path in the message history.
    *   Add a `read_context_file(path)` tool so the agent can retrieve details on demand.

### Phase 13: Proof-of-Exploit (PoE) & Verification Agent (Medium Priority)
**Goal:** Implement mandatory exploit validation to eliminate false positives, inspired by MAPTA and Manus AI's Verification Agent.

**Implementation Steps:**
1.  **Create `core/validator.py`**:
    *   Define a new agent role: `Validation Oracle` (or Verification Agent).
    *   When the `executor` claims a vulnerability is found, the `validator` must generate a safe, non-destructive script (e.g., `id` or `whoami` via RCE, or a benign SQL `SELECT`) to prove it.
2.  **Update `core/multiagent.py`**:
    *   Integrate the `validator` into the `MultiAgentOrchestrator`.
    *   Require the `boss_synthesis` to include the output of the validation script before marking a subtask as "Success".

### Phase 14: Dynamic Search & OSINT Integration (Medium Priority)
**Goal:** Allow Agent-Nimi to research unknown CVEs and exploits dynamically, similar to Manus AI's "Wide Research" capability.

**Implementation Steps:**
1.  **Create `tools/osint_tools.py`**:
    *   Implement `web_search(query)` using an API like Tavily, DuckDuckGo, or Google Custom Search.
    *   Implement `github_search(query)` to find public exploit PoCs.
2.  **Update `core/multiagent.py`**:
    *   Assign the `osint_tools` exclusively to the `researcher` role to enforce separation of concerns.

### Phase 15: Dynamic Tool Masking & Orchestration (Low Priority)
**Goal:** Move away from rigid tool whitelists to Manus AI's approach of context-aware logit masking and dual-loop orchestration.

**Implementation Steps:**
1.  **Refactor `core/progress.py`**:
    *   Rename `ProgressLedger` to `InnerProgressLedger` (tracks immediate tool execution).
    *   Create `OuterTaskLedger` (tracks high-level plan, facts, and guesses).
2.  **Update `core/workflows.py`**:
    *   Instead of hard-failing when an un-whitelisted tool is called, implement constrained decoding or system prompt instructions that dynamically hide tools based on the current state in the `OuterTaskLedger`.

---

## References

1. [arXiv: From Mind to Machine: The Rise of Manus AI as a Fully Autonomous Digital Agent](https://arxiv.org/html/2505.02024v3)
2. [Manus AI Blog: Context Engineering for AI Agents](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
3. [Microsoft Research: Magentic-One: A Generalist Multi-Agent System for Solving Complex Tasks](https://www.microsoft.com/en-us/research/articles/magentic-one-a-generalist-multi-agent-system-for-solving-complex-tasks/)
4. [GitHub: vxcontrol/pentagi](https://github.com/vxcontrol/pentagi)
5. [arXiv: Multi-Agent Penetration Testing AI for the Web (MAPTA)](https://arxiv.org/abs/2508.20816)
