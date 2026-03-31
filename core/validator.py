"""
Exploit Validator — Phase 13
─────────────────────────────
Validates whether shell output or agent claims actually constitute a
confirmed exploit/successful compromise.

Used by the multiagent boss synthesis to score executor output and annotate
results with confidence levels before presenting them to the user.

Inspired by PentAGI's confirmation-before-reporting requirement.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ConfidenceLevel(str, Enum):
    CONFIRMED = "confirmed"       # Strong evidence of successful exploitation
    PROBABLE  = "probable"        # Multiple weak signals, needs human review
    UNVERIFIED = "unverified"     # Claimed but no evidence in output
    FAILED    = "failed"          # Output shows explicit failure


@dataclass
class ValidationResult:
    confidence: ConfidenceLevel
    score: float                  # 0.0–1.0
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommendation: str = ""

    def to_annotation(self) -> str:
        """Short annotation string for embedding in multiagent reports."""
        icon = {
            ConfidenceLevel.CONFIRMED:  "✅ CONFIRMED",
            ConfidenceLevel.PROBABLE:   "🟡 PROBABLE",
            ConfidenceLevel.UNVERIFIED: "❓ UNVERIFIED",
            ConfidenceLevel.FAILED:     "❌ FAILED",
        }[self.confidence]
        lines = [f"[Validator: {icon}  score={self.score:.2f}]"]
        if self.evidence:
            lines.append("Evidence: " + "; ".join(self.evidence[:3]))
        if self.warnings:
            lines.append("Warnings: " + "; ".join(self.warnings[:2]))
        if self.recommendation:
            lines.append(f"Rec: {self.recommendation}")
        return "\n".join(lines)


# ── Patterns ──────────────────────────────────────────────────────────────────

# Hard evidence of root/SYSTEM shell
_ROOT_SHELL_PATTERNS = [
    re.compile(r"\broot@\w", re.IGNORECASE),
    re.compile(r"\buid=0\(root\)", re.IGNORECASE),
    re.compile(r"SYSTEM\s*>", re.IGNORECASE),
    re.compile(r"NT AUTHORITY\\SYSTEM", re.IGNORECASE),
    re.compile(r"whoami.*\broot\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\broot\b.*#\s*$", re.IGNORECASE | re.MULTILINE),
]

# Shell / command execution evidence
_EXEC_EVIDENCE_PATTERNS = [
    re.compile(r"\$\s+(?:whoami|id|uname|cat\s+/etc/passwd)", re.IGNORECASE),
    re.compile(r"command not found", re.IGNORECASE),  # negative — only if expected
    re.compile(r"\[\+\]\s+(?:got|obtained|established|shell|session)", re.IGNORECASE),
    re.compile(r"meterpreter\s*>", re.IGNORECASE),
    re.compile(r"msf\d*\s*>", re.IGNORECASE),
    re.compile(r"\[msf\]", re.IGNORECASE),
    re.compile(r"shell\s+opened", re.IGNORECASE),
    re.compile(r"session \d+ opened", re.IGNORECASE),
    re.compile(r"connection established", re.IGNORECASE),
    re.compile(r"reverse shell.*connected", re.IGNORECASE | re.DOTALL),
]

# Network/service access evidence
_ACCESS_PATTERNS = [
    re.compile(r"login successful", re.IGNORECASE),
    re.compile(r"authenticated successfully", re.IGNORECASE),
    re.compile(r"access granted", re.IGNORECASE),
    re.compile(r"logged in as", re.IGNORECASE),
    re.compile(r"\bHTTP/1\.[01]\s+200\b"),
    re.compile(r"password.*accepted", re.IGNORECASE),
    re.compile(r"found credentials?:", re.IGNORECASE),
    re.compile(r"valid credentials?", re.IGNORECASE),
    re.compile(r"\[SUCCESS\]", re.IGNORECASE),
]

# Negative patterns — clear failures
_FAILURE_PATTERNS = [
    re.compile(r"authentication failed", re.IGNORECASE),
    re.compile(r"permission denied", re.IGNORECASE),
    re.compile(r"access denied", re.IGNORECASE),
    re.compile(r"connection refused", re.IGNORECASE),
    re.compile(r"exploit failed", re.IGNORECASE),
    re.compile(r"target is not vulnerable", re.IGNORECASE),
    re.compile(r"\bERROR\b.*\bno such\b", re.IGNORECASE),
    re.compile(r"unreachable", re.IGNORECASE),
    re.compile(r"timed out", re.IGNORECASE),
]

# Claim-without-evidence patterns (in agent text, not shell output)
_UNSUBSTANTIATED_CLAIMS = [
    re.compile(r"i have (gained|obtained) (root|shell|access)", re.IGNORECASE),
    re.compile(r"successfully exploited", re.IGNORECASE),
    re.compile(r"exploit (was|is) successful", re.IGNORECASE),
    re.compile(r"gained (root|admin|system|shell)", re.IGNORECASE),
    re.compile(r"the target (is|has been) compromised", re.IGNORECASE),
]


# ── ExploitValidator ──────────────────────────────────────────────────────────

class ExploitValidator:
    """Validate shell output and agent text for exploit confirmation evidence."""

    def validate(self, agent_text: str, shell_output: str = "") -> ValidationResult:
        """
        Validate an exploit claim.

        Args:
            agent_text:   The agent's claim / summary text.
            shell_output: Raw shell command output (if any) to check against.

        Returns:
            ValidationResult with confidence level, score, and evidence list.
        """
        combined = f"{shell_output}\n{agent_text}"
        evidence: list[str] = []
        warnings: list[str] = []
        score = 0.0
        root_shell_hit = False

        # ── Check for confirmed root/SYSTEM shell ─────────────────────────
        for pat in _ROOT_SHELL_PATTERNS:
            m = pat.search(combined)
            if m:
                evidence.append(f"Root shell indicator: {m.group(0)[:60].strip()!r}")
                score += 0.55   # one root-shell indicator is enough for CONFIRMED
                root_shell_hit = True

        # ── Check for shell/session execution evidence ────────────────────
        exec_hits = 0
        for pat in _EXEC_EVIDENCE_PATTERNS:
            m = pat.search(combined)
            if m:
                snippet = m.group(0)[:60].strip()
                evidence.append(f"Exec evidence: {snippet!r}")
                exec_hits += 1
                score += 0.15
                if exec_hits >= 3:
                    break

        # ── Check for access/auth success ─────────────────────────────────
        access_hits = 0
        for pat in _ACCESS_PATTERNS:
            m = pat.search(combined)
            if m:
                evidence.append(f"Access evidence: {m.group(0)[:60].strip()!r}")
                access_hits += 1
                score += 0.1
                if access_hits >= 3:
                    break

        # ── Check for unsubstantiated claims in AGENT text (not shell output) ─
        claim_hits = 0
        for pat in _UNSUBSTANTIATED_CLAIMS:
            m = pat.search(agent_text)
            if m and not pat.search(shell_output):
                warnings.append(f"Unverified claim in agent text: {m.group(0)[:60].strip()!r}")
                claim_hits += 1

        # ── Check for failures ────────────────────────────────────────────
        failure_hits = 0
        for pat in _FAILURE_PATTERNS:
            m = pat.search(combined)
            if m:
                warnings.append(f"Failure indicator: {m.group(0)[:60].strip()!r}")
                failure_hits += 1
                score -= 0.2

        # ── Cap + clamp score ─────────────────────────────────────────────
        score = max(0.0, min(1.0, score))

        # ── Determine confidence level ────────────────────────────────────
        if failure_hits > 0 and score < 0.1:
            confidence = ConfidenceLevel.FAILED
            recommendation = "Review failure reasons and try an alternative approach or different exploit vector."
        elif score >= 0.5 and evidence:
            confidence = ConfidenceLevel.CONFIRMED
            recommendation = "Document findings and proceed with post-exploitation or report generation."
        elif score >= 0.2 or (evidence and not warnings):
            confidence = ConfidenceLevel.PROBABLE
            recommendation = "Gather additional evidence — run 'id', 'whoami', or capture a flag before claiming success."
        else:
            confidence = ConfidenceLevel.UNVERIFIED
            if claim_hits > 0:
                recommendation = "Agent claims success but shell output does not corroborate it. Re-run with verbose output."
            else:
                recommendation = "No exploitation evidence found. This may be reconnaissance output only."

        return ValidationResult(
            confidence=confidence,
            score=round(score, 3),
            evidence=evidence,
            warnings=warnings,
            recommendation=recommendation,
        )

    def validate_executor_output(self, results: dict[str, Any]) -> dict[str, ValidationResult]:
        """
        Validate all executor role outputs in a multiagent results dict.

        Args:
            results: The ``results`` dict from MultiAgentOrchestrator.run_mission().

        Returns:
            Dict mapping role name → ValidationResult for executor-type roles.
        """
        validated: dict[str, ValidationResult] = {}
        for role, entry in results.items():
            if role not in ("executor", "planner"):
                continue
            output = entry.get("output", "")
            vr = self.validate(agent_text=output, shell_output="")
            validated[role] = vr
        return validated

    def annotate_results(self, results: dict[str, Any]) -> dict[str, Any]:
        """
        Return a copy of the results dict with validator annotations injected
        into executor/planner outputs.
        """
        validated = self.validate_executor_output(results)
        annotated = {}
        for role, entry in results.items():
            new_entry = dict(entry)
            if role in validated:
                vr = validated[role]
                annotation = vr.to_annotation()
                new_entry["output"] = f"{entry.get('output', '')}\n\n{annotation}"
                new_entry["validation"] = {
                    "confidence": vr.confidence.value,
                    "score": vr.score,
                    "evidence": vr.evidence,
                    "warnings": vr.warnings,
                }
            annotated[role] = new_entry
        return annotated
