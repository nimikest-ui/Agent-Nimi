"""
Workflow Engine (Phase 9)
─────────────────────────
Provides reusable, multi-step workflow pipelines that chain LLM calls
with optional tool whitelists and gate functions.

A Workflow is a named sequence of WorkflowSteps.  Each step has:
  - prompt template (with ``{context}`` placeholder)
  - optional tools_allowed whitelist (empty = no tools, None = all tools)
  - optional gate callable that decides whether to continue

Usage:
    from core.workflows import RECON_WORKFLOW, run_workflow
    result = run_workflow(agent, RECON_WORKFLOW, initial_input="10.0.0.1")
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.audit import audit_event


# ─── Data structures ──────────────────────────────────────────────────────────

@dataclass
class WorkflowStep:
    """A single step in a workflow pipeline."""
    name: str
    prompt_template: str  # must contain ``{context}``
    tools_allowed: Optional[list[str]] = None  # None = all, [] = no tools
    gate: Optional[Callable[[str], bool]] = None  # return False to abort

    def render_prompt(self, context: str) -> str:
        return self.prompt_template.format(context=context)


@dataclass
class WorkflowResult:
    """Outcome of a workflow run."""
    workflow_name: str
    success: bool
    final_output: str
    steps_completed: int
    total_steps: int
    aborted_at: Optional[str] = None  # step name where gate failed
    step_outputs: list[dict] = field(default_factory=list)
    elapsed: float = 0.0


@dataclass
class Workflow:
    """Named sequence of steps that form a reusable pipeline."""
    name: str
    description: str
    steps: list[WorkflowStep]
    tags: list[str] = field(default_factory=list)


# ─── Runner ───────────────────────────────────────────────────────────────────

def run_workflow(
    agent,
    workflow: Workflow,
    initial_input: str,
    stream_callback=None,
) -> WorkflowResult:
    """Execute a workflow against the agent, chaining step outputs.

    Each step is run through the agent's ``_agent_loop`` (single-agent mode)
    with an optional tool whitelist.  If a gate function returns False the
    workflow is aborted early.
    """
    context = initial_input
    step_outputs: list[dict] = []
    start = time.time()
    # Snapshot messages before workflow begins; step prompts are scoped and
    # do not persist into the main conversation after the workflow completes.
    _pre_workflow_messages = list(agent.messages)

    audit_event("workflow_start", {
        "workflow": workflow.name,
        "steps": len(workflow.steps),
        "input_preview": initial_input[:400],
    })

    if stream_callback:
        stream_callback({
            "event": "workflow_start",
            "workflow": workflow.name,
            "total_steps": len(workflow.steps),
        })

    for idx, step in enumerate(workflow.steps):
        step_start = time.time()

        if stream_callback:
            stream_callback({
                "event": "workflow_step",
                "step": idx + 1,
                "total": len(workflow.steps),
                "name": step.name,
            })

        prompt = step.render_prompt(context)

        # Build a scoped message list: pre-workflow snapshot + step prompt.
        # agent.messages is swapped for the duration of _agent_loop so step
        # prompts and intermediate tool calls don't pollute future conversations.
        _step_messages = list(_pre_workflow_messages)
        _step_messages.append({"role": "user", "content": prompt})

        # Save & apply tool whitelist + scoped messages
        _original_messages = agent.messages
        _original_tools_allowed = getattr(agent, "_workflow_tools_allowed", None)
        agent.messages = _step_messages
        agent._workflow_tools_allowed = step.tools_allowed

        try:
            result = agent._agent_loop(stream_callback)
        finally:
            # Restore messages and tool whitelist
            agent.messages = _original_messages
            agent._workflow_tools_allowed = _original_tools_allowed

        step_elapsed = time.time() - step_start

        step_outputs.append({
            "step": idx + 1,
            "name": step.name,
            "output_preview": result[:500] if result else "",
            "elapsed": round(step_elapsed, 2),
        })

        audit_event("workflow_step_done", {
            "workflow": workflow.name,
            "step": step.name,
            "step_num": idx + 1,
            "elapsed": round(step_elapsed, 2),
        })

        # Gate check
        if step.gate and not step.gate(result):
            audit_event("workflow_gate_failed", {
                "workflow": workflow.name,
                "step": step.name,
            })
            if stream_callback:
                stream_callback({
                    "event": "workflow_gate_failed",
                    "step": step.name,
                })
            return WorkflowResult(
                workflow_name=workflow.name,
                success=False,
                final_output=result,
                steps_completed=idx + 1,
                total_steps=len(workflow.steps),
                aborted_at=step.name,
                step_outputs=step_outputs,
                elapsed=round(time.time() - start, 2),
            )

        context = result

    elapsed = round(time.time() - start, 2)
    audit_event("workflow_done", {
        "workflow": workflow.name,
        "steps_completed": len(workflow.steps),
        "elapsed": elapsed,
    })
    if stream_callback:
        stream_callback({
            "event": "workflow_done",
            "workflow": workflow.name,
            "steps_completed": len(workflow.steps),
            "elapsed": elapsed,
        })

    return WorkflowResult(
        workflow_name=workflow.name,
        success=True,
        final_output=context,
        steps_completed=len(workflow.steps),
        total_steps=len(workflow.steps),
        step_outputs=step_outputs,
        elapsed=elapsed,
    )


# ─── Gate helpers ─────────────────────────────────────────────────────────────

def _not_empty(result: str) -> bool:
    """Gate: abort if result is empty or just whitespace."""
    return bool(result and result.strip())


def _has_findings(result: str) -> bool:
    """Gate: abort if the scan/analysis produced nothing useful."""
    if not result or not result.strip():
        return False
    lower = result.lower()
    negative_markers = [
        "no results", "nothing found", "no open ports",
        "no vulnerabilities", "scan failed", "error:",
        "host seems down", "0 hosts up",
    ]
    return not any(marker in lower for marker in negative_markers)


# ─── Pre-built Workflows ─────────────────────────────────────────────────────

RECON_WORKFLOW = Workflow(
    name="recon",
    description="Full reconnaissance pipeline: enumerate → OSINT enrich → analyze → report",
    steps=[
        WorkflowStep(
            name="enumerate",
            prompt_template=(
                "Perform comprehensive reconnaissance on {context}. "
                "Run subdomain enumeration, port scanning, and service detection. "
                "Gather as much information as possible about the target."
            ),
            tools_allowed=["nmap_scan", "shell_exec", "file_read"],
            gate=_not_empty,
        ),
        WorkflowStep(
            name="osint_enrich",
            prompt_template=(
                "Enrich these recon results with OSINT data. For each discovered "
                "service/version, run cve_lookup. Run whois_lookup on the target "
                "domain/IP. Use web_search to find known issues, default creds, "
                "or advisories. Use github_search if any custom software is detected.\n\n"
                "{context}"
            ),
            tools_allowed=["web_search", "cve_lookup", "github_search", "whois_lookup",
                           "shodan_host", "searchsploit", "shell_exec"],
            gate=_not_empty,
        ),
        WorkflowStep(
            name="analyze",
            prompt_template=(
                "Analyze these reconnaissance results and identify potential "
                "vulnerabilities, misconfigurations, and attack vectors:\n\n{context}"
            ),
            tools_allowed=["searchsploit", "shell_exec"],
            gate=_not_empty,
        ),
        WorkflowStep(
            name="report",
            prompt_template=(
                "Write a professional penetration testing reconnaissance report "
                "based on the following findings. Include an executive summary, "
                "detailed findings, risk ratings, and recommendations:\n\n{context}"
            ),
            tools_allowed=["file_write"],
        ),
    ],
    tags=["security", "recon", "scan"],
)

EXPLOIT_WORKFLOW = Workflow(
    name="exploit",
    description="Exploit development pipeline: research → develop → validate",
    steps=[
        WorkflowStep(
            name="research",
            prompt_template=(
                "Research known vulnerabilities and exploits for the following "
                "target/service. Use cve_lookup for specific CVE IDs, web_search for "
                "advisories and PoCs, github_search for exploit code, and searchsploit "
                "for local Exploit-DB matches:\n\n{context}"
            ),
            tools_allowed=["searchsploit", "shell_exec", "file_read",
                           "web_search", "cve_lookup", "github_search"],
            gate=_has_findings,
        ),
        WorkflowStep(
            name="develop",
            prompt_template=(
                "Based on this vulnerability research, develop a proof-of-concept "
                "exploit or attack plan. Write any necessary scripts:\n\n{context}"
            ),
            tools_allowed=["file_write", "shell_exec"],
            gate=_not_empty,
        ),
        WorkflowStep(
            name="validate",
            prompt_template=(
                "Review and validate this exploit / attack plan for correctness, "
                "safety, and effectiveness. Test the approach where possible and "
                "suggest concrete improvements:\n\n{context}"
            ),
            tools_allowed=["shell_exec", "nmap_scan", "file_read"],
        ),
    ],
    tags=["security", "exploit", "offensive"],
)

ANALYSIS_WORKFLOW = Workflow(
    name="analysis",
    description="Deep analysis pipeline: gather data → analyze → synthesize",
    steps=[
        WorkflowStep(
            name="gather",
            prompt_template=(
                "Gather all relevant data and information about the following "
                "topic. Read files, check system state, and collect evidence:\n\n{context}"
            ),
            tools_allowed=["file_read", "shell_exec", "system_status"],
            gate=_not_empty,
        ),
        WorkflowStep(
            name="analyze",
            prompt_template=(
                "Perform deep analysis of the gathered data. Identify patterns, "
                "anomalies, and key insights:\n\n{context}"
            ),
            tools_allowed=["shell_exec"],
            gate=_not_empty,
        ),
        WorkflowStep(
            name="synthesize",
            prompt_template=(
                "Synthesize all findings into a clear, actionable summary with "
                "prioritized recommendations:\n\n{context}"
            ),
            tools_allowed=["file_write"],
        ),
    ],
    tags=["analysis", "research"],
)

HARDENING_WORKFLOW = Workflow(
    name="hardening",
    description="System hardening pipeline: audit → fix → verify",
    steps=[
        WorkflowStep(
            name="audit",
            prompt_template=(
                "Perform a security audit of the system focusing on: {context}. "
                "Check configurations, permissions, running services, and open ports."
            ),
            tools_allowed=["shell_exec", "file_read", "system_status", "service_status"],
            gate=_not_empty,
        ),
        WorkflowStep(
            name="fix",
            prompt_template=(
                "Based on this security audit, implement the necessary hardening "
                "measures. Fix misconfigurations and close unnecessary services:\n\n{context}"
            ),
            tools_allowed=["shell_exec", "file_write"],
            gate=_not_empty,
        ),
        WorkflowStep(
            name="verify",
            prompt_template=(
                "Verify that the hardening measures were applied correctly. "
                "Re-check the items from the original audit:\n\n{context}"
            ),
            tools_allowed=["shell_exec", "file_read", "system_status"],
        ),
    ],
    tags=["security", "hardening", "defense"],
)


# ─── Registry ─────────────────────────────────────────────────────────────────

WORKFLOW_REGISTRY: dict[str, Workflow] = {
    wf.name: wf
    for wf in [RECON_WORKFLOW, EXPLOIT_WORKFLOW, ANALYSIS_WORKFLOW, HARDENING_WORKFLOW]
}


def get_workflow(name: str) -> Optional[Workflow]:
    """Look up a workflow by name."""
    return WORKFLOW_REGISTRY.get(name)


def list_workflows() -> list[dict]:
    """Return summary info for all registered workflows."""
    return [
        {
            "name": wf.name,
            "description": wf.description,
            "steps": len(wf.steps),
            "step_names": [s.name for s in wf.steps],
            "tags": wf.tags,
        }
        for wf in WORKFLOW_REGISTRY.values()
    ]


def detect_workflow(user_input: str, min_keyword_score: int = 2) -> Optional[Workflow]:
    """Try to match user input to a pre-built workflow.

    Returns the workflow if a strong match is found, else None.
    Uses keyword heuristics (not LLM) for speed.
    """
    text = (user_input or "").lower().strip()
    if not text:
        return None

    # Explicit workflow invocation: "run recon workflow on ..."
    for name, wf in WORKFLOW_REGISTRY.items():
        if f"{name} workflow" in text or f"run {name}" in text:
            return wf

    # Keyword-based matching
    scores: dict[str, int] = {}
    keyword_map = {
        "recon": ["recon", "reconnaissance", "enumerate", "scan ports", "scan target",
                   "subdomain", "fingerprint", "service detection", "full scan"],
        "exploit": ["exploit", "attack", "pwn", "payload", "rce", "reverse shell",
                     "proof of concept", "poc", "privilege escalation"],
        "analysis": ["analyze", "analysis", "investigate", "forensic", "review logs",
                      "incident", "deep dive", "examine"],
        "hardening": ["harden", "hardening", "secure", "lockdown", "lock down",
                       "patch", "baseline", "cis benchmark", "audit security"],
    }

    for wf_name, keywords in keyword_map.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[wf_name] = score

    if not scores:
        return None

    # Need at least 2 keyword hits to auto-trigger a workflow
    best_name = max(scores, key=scores.get)
    if scores[best_name] >= min_keyword_score:
        return WORKFLOW_REGISTRY.get(best_name)

    return None
