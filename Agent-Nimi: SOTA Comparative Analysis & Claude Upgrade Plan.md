# Agent-Nimi: SOTA Comparative Analysis & Claude Upgrade Plan

This document provides a feature-by-feature comparison of Agent-Nimi against leading AI agent frameworks of 2026 (Microsoft Magentic-One, PentAGI, MAPTA, Devin), followed by a detailed, file-level implementation plan for upgrading Agent-Nimi to the current state-of-the-art.

![Agent-Nimi vs. Leading AI Agent Projects](https://private-us-east-1.manuscdn.com/sessionFile/Dli0kJSh4HFPbX00KgdXFu/sandbox/ZhpPJGKXIzsCFqF4vLDkwZ-images_1775405871935_na1fn_L2hvbWUvdWJ1bnR1L3JhZGFyX2NvbXBhcmlzb24.png?Policy=eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6Ly9wcml2YXRlLXVzLWVhc3QtMS5tYW51c2Nkbi5jb20vc2Vzc2lvbkZpbGUvRGxpMGtKU2g0SEZQYlgwMEtnZFhGdS9zYW5kYm94L1pocFBKR0tYSXpzQ0ZxRjR2TERrd1otaW1hZ2VzXzE3NzU0MDU4NzE5MzVfbmExZm5fTDJodmJXVXZkV0oxYm5SMUwzSmhaR0Z5WDJOdmJYQmhjbWx6YjI0LnBuZyIsIkNvbmRpdGlvbiI6eyJEYXRlTGVzc1RoYW4iOnsiQVdTOkVwb2NoVGltZSI6MTc5ODc2MTYwMH19fV19&Key-Pair-Id=K2HSFNDJXOU9YS&Signature=sYFOdHFzhPEQRX56huq2zPvYoBUm-IIffaHiQnC5BUZriXFI6aVOzQ5C4cn2RX0xcVx248wSRCCY-5eStYvGQsQ45QMfvkWlZl2qrKa-sW6X2aVKkNQ5WGa-ItS8RIG2mKyX7Cu97dbkkeGPwK-N~k1Ivr2mEXVsHFrSdYAQRX5XGPIn3eAg6OWCjku8pPW1VHFNpTiHI7xjMRkhyJr6RUpGktignJLVAwxdKMUQkHHAs13pzhWh7gCE3Y8iZkbwyc6MG7mZcielp0dOhYGRli~3GMdsDYjansULE~tDhjo4NuXQVzGtHM6dy8vbStPxSnlrAETD~R71sNoRVfXmfA__)

---

## 1. Feature-by-Feature Comparison Matrix

| Feature | Agent-Nimi | Microsoft Magentic-One [1] | PentAGI [2] | MAPTA [3] | Strategic Gap |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Multi-Agent Orchestration** | Fixed 5 roles (`multiagent.py`) | Dynamic Orchestrator + 4 specialists | 13+ specialized roles | Coordinator + Sandbox + Validation | **Moderate**: Agent-Nimi lacks dynamic sub-agent spawning and role scaling. |
| **Browser & Vision** | None (Text/CLI only) | WebSurfer (Accessibility Tree + Set-of-Marks) | Built-in web scraper | Headless browser integration | **High**: Agent-Nimi is blind to web GUIs and visual context. |
| **Execution Environment** | Direct Kali execution | Local shell / Docker | Isolated Docker per task | Shared per-job Docker | **Moderate**: Agent-Nimi needs better sandboxing for untrusted exploit execution. |
| **Memory & State** | Episodic + Fact KV (`fact_memory.py`) | Task Ledger + Progress Ledger | Neo4j Knowledge Graph | Short-term context | **High**: Agent-Nimi's `world_state.py` is flat; needs graph-based tracking. |
| **Self-Correction** | Reflexion (post-hoc, max 2) | Outer loop replanning | Mentor/Adviser intervention | Proof-of-Exploit Oracle | **High**: Agent-Nimi needs proactive "Think-Before-Act" critique and exploit validation. |
| **Search Integration** | None (relies on local tools) | WebSurfer search | 7+ Search Engines (Tavily, etc.) | Web search | **Moderate**: Agent-Nimi cannot dynamically research new CVEs online. |

---

## 2. Claude-Ready Implementation Plan

This section outlines the specific architectural changes required to upgrade Agent-Nimi. Provide this plan to Claude for implementation.

### Phase 11: Multimodal Vision & Browser Integration (High Priority)
**Goal:** Enable Agent-Nimi to interact with web applications visually, closing the gap with Magentic-One's WebSurfer.

**Implementation Steps:**
1.  **Create `tools/browser_tools.py`**:
    *   Implement a headless browser tool using Playwright or Selenium.
    *   Add functions: `browser_navigate(url)`, `browser_screenshot(element_id)`, `browser_click(element_id)`, `browser_type(element_id, text)`.
    *   Implement a "Set-of-Marks" function that annotates screenshots with numbered bounding boxes over interactive elements.
2.  **Update `providers/base.py` & `providers/grok_provider.py`**:
    *   Add support for multimodal inputs (passing base64 images to `grok-vision-beta` or `gpt-4o`).
3.  **Update `core/agent.py`**:
    *   When a browser tool returns a screenshot, inject the image into the message history for the next LLM call.

### Phase 12: Knowledge Graph World State (High Priority)
**Goal:** Upgrade `world_state.py` from flat dictionaries to a semantic knowledge graph, similar to PentAGI's Neo4j integration.

**Implementation Steps:**
1.  **Refactor `core/world_state.py`**:
    *   Introduce a lightweight graph structure (e.g., using `networkx` or a simple node/edge dictionary).
    *   Nodes: `Host`, `Port`, `Service`, `User`, `File`, `Vulnerability`.
    *   Edges: `HAS_PORT`, `RUNS_SERVICE`, `OWNED_BY`, `CONTAINS_VULN`.
2.  **Update `_handle_nmap` and `_handle_shell_exec`**:
    *   Instead of updating a flat dict, add nodes and edges. For example, `nmap` output creates a `Host` node connected to `Port` nodes via `HAS_PORT`.
3.  **Enhance `summary()`**:
    *   Generate a textual representation of the graph (e.g., "Host 10.0.0.1 HAS_PORT 80 RUNS_SERVICE nginx") to inject into the LLM context.

### Phase 13: Proof-of-Exploit (PoE) Validation (Medium Priority)
**Goal:** Implement mandatory exploit validation to eliminate false positives, inspired by MAPTA.

**Implementation Steps:**
1.  **Create `core/validator.py`**:
    *   Define a new agent role: `Validation Oracle`.
    *   When the `executor` claims a vulnerability is found, the `validator` must generate a safe, non-destructive script (e.g., `id` or `whoami` via RCE, or a benign SQL `SELECT`) to prove it.
2.  **Update `core/multiagent.py`**:
    *   Integrate the `validator` into the `MultiAgentOrchestrator`.
    *   Require the `boss_synthesis` to include the output of the validation script before marking a subtask as "Success".

### Phase 14: Dynamic Search & OSINT Integration (Medium Priority)
**Goal:** Allow Agent-Nimi to research unknown CVEs and exploits dynamically.

**Implementation Steps:**
1.  **Create `tools/osint_tools.py`**:
    *   Implement `web_search(query)` using an API like Tavily, DuckDuckGo, or Google Custom Search.
    *   Implement `github_search(query)` to find public exploit PoCs.
2.  **Update `core/multiagent.py`**:
    *   Assign the `osint_tools` exclusively to the `researcher` role to enforce separation of concerns.

### Phase 15: Dual-Loop Orchestration (Low Priority)
**Goal:** Move from a single iteration limit to Magentic-One's Task Ledger (Outer) and Progress Ledger (Inner) loops.

**Implementation Steps:**
1.  **Refactor `core/progress.py`**:
    *   Rename `ProgressLedger` to `InnerProgressLedger` (tracks immediate tool execution).
    *   Create `OuterTaskLedger` (tracks high-level plan, facts, and guesses).
2.  **Update `core/agent.py` (`_agent_loop`)**:
    *   Implement the outer loop: If `InnerProgressLedger.is_stalled()` is true, break to the outer loop, update the `OuterTaskLedger` with the failure reason, and generate a new plan before restarting the inner loop.

---

## References

1. [Microsoft Research: Magentic-One: A Generalist Multi-Agent System for Solving Complex Tasks](https://www.microsoft.com/en-us/research/articles/magentic-one-a-generalist-multi-agent-system-for-solving-complex-tasks/)
2. [GitHub: vxcontrol/pentagi](https://github.com/vxcontrol/pentagi)
3. [arXiv: Multi-Agent Penetration Testing AI for the Web (MAPTA)](https://arxiv.org/abs/2508.20816)
