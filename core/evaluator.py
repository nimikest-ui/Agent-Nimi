"""
Auto-Evaluator
──────────────
Scores LLM responses on quality, latency, and cost.
Quality is estimated via heuristics (no second LLM call needed).
When heuristic quality is low and semantic evaluation is enabled,
a cheap LLM judge provides a second opinion (Phase 6).
"""
import json
import math
import re
import time

# Rough cost per 1K tokens (output), USD
# Used only for relative scoring — doesn't need to be exact
# Prices sourced from xAI docs (docs.x.ai/docs/models) — output price / 1M → /1000
MODEL_COST_PER_1K: dict[str, float] = {
    # Grok — grok-4.20 family ($6/1M out = $0.006/1K)
    "grok-4.20": 0.006,
    "grok-4.20-0309-reasoning": 0.006,
    "grok-4.20-0309-non-reasoning": 0.006,
    "grok-4.20-multi-agent-0309": 0.006,
    # Grok — grok-4 family
    "grok-4": 0.015,      # $15/1M out (same tier as grok-3)
    "grok-4-fast": 0.0005, # $0.50/1M out (alias: grok-4-fast-reasoning)
    # Grok — grok-4-1-fast family ($0.50/1M out = $0.0005/1K)
    "grok-4-1-fast-reasoning": 0.0005,
    "grok-4-1-fast-non-reasoning": 0.0005,
    # Grok — grok-3 family
    "grok-3": 0.015,           # $15/1M out
    "grok-3-fast": 0.015,      # alias for grok-3, same price
    "grok-3-mini": 0.0005,     # $0.50/1M out
    "grok-3-mini-fast": 0.0005, # alias for grok-3-mini, same price
    # Grok — grok-2 family ($10/1M out)
    "grok-2-1212": 0.010,
    "grok-2-vision-1212": 0.010,
    "grok-vision-beta": 0.010,
    "grok-beta": 0.010,
    # OpenRouter pass-through estimates
    "gpt-4o": 0.015,
    "gpt-4o-mini": 0.003,
    "gpt-4-turbo": 0.030,
    "claude-3.5-sonnet": 0.015,
    "claude-3-opus": 0.075,
    "claude-3-haiku": 0.001,
    "llama-3-70b-instruct": 0.001,
    "llama-3.1-405b-instruct": 0.005,
    "deepseek-chat": 0.001,
    "deepseek-r1": 0.003,
    "gemini-pro-1.5": 0.007,
    "mistral-large": 0.008,
    # Copilot CLI models - rough relative estimates only
    "claude-sonnet-4.5": 0.015,
    "claude-sonnet-4.6": 0.018,
    "claude-haiku-4.5": 0.001,
    "gpt-5.2": 0.020,
    "gpt-5.3-codex": 0.025,
}

# GitHub Copilot premium request multipliers for paid plans.
# 0 means the model is included and does not consume premium requests on Pro.
COPILOT_PREMIUM_MULTIPLIER: dict[str, float] = {
    "gpt-4.1": 0.0,
    "gpt-4o": 0.0,
    "gpt-5-mini": 0.0,
    "claude-haiku-4.5": 0.33,
    "gpt-5.1-codex-mini": 0.33,
    "grok-code-fast-1": 0.25,
    "claude-sonnet-4": 1.0,
    "claude-sonnet-4.5": 1.0,
    "claude-sonnet-4.6": 1.0,
    "gpt-5.1": 1.0,
    "gpt-5.2": 1.0,
    "gpt-5.2-codex": 1.0,
    "gpt-5.3-codex": 1.0,
    "gpt-5.4": 1.0,
    "claude-opus-4.5": 3.0,
    "claude-opus-4.6": 3.0,
}


def get_copilot_multiplier(model: str) -> float:
    """Return the Copilot premium-request multiplier for a model."""
    model_short = (model.split("/")[-1] if model else "").lower()
    mult = COPILOT_PREMIUM_MULTIPLIER.get(model_short)
    if mult is None:
        for key, value in COPILOT_PREMIUM_MULTIPLIER.items():
            if key in model_short or model_short in key:
                mult = value
                break
    return 1.0 if mult is None else float(mult)


class AutoEvaluator:
    """Evaluate an LLM response and return normalized scores."""

    def evaluate(
        self,
        prompt: str,
        response: str,
        provider: str,
        model: str,
        latency_seconds: float,
        tool_calls: int = 0,
        tool_successes: int = 0,
    ) -> dict:
        """Score a response.
        
        Returns:
            {
                "quality": float 0-1,
                "latency": float 0-1 (higher = faster),
                "cost":    float 0-1 (higher = cheaper),
                "task_type": str,
                "issues":  list[str],
            }
        """
        task_type = self.classify_task(prompt)
        quality, issues = self._quality_score(prompt, response, tool_calls, tool_successes, task_type)
        latency = self._latency_score(latency_seconds)
        cost = self._cost_score(provider, model, response)

        return {
            "quality": round(quality, 4),
            "latency": round(latency, 4),
            "cost": round(cost, 4),
            "task_type": task_type,
            "issues": issues,
        }

    def evaluate_quick(self, prompt: str, response: str,
                       tool_calls: int = 0, tool_successes: int = 0) -> dict:
        """Lightweight evaluation returning only quality + issues (no cost/latency).

        Used by the Reflexion retry loop to decide whether to refine.
        """
        task_type = self.classify_task(prompt)
        quality, issues = self._quality_score(prompt, response, tool_calls, tool_successes, task_type)
        return {
            "quality": round(quality, 4),
            "task_type": task_type,
            "issues": issues,
        }

    # ─── Semantic (LLM-judge) evaluation (Phase 6) ───

    _EVAL_PROMPT = (
        "Rate this AI response to the given task.\n\n"
        "Task: {task}\n\n"
        "Response:\n{response}\n\n"
        "Score each dimension 1-10:\n"
        "- relevance: Does the response address the task?\n"
        "- correctness: Is the information accurate?\n"
        "- completeness: Are all parts of the task covered?\n"
        "- conciseness: Is it focused without unnecessary padding?\n\n"
        "Return ONLY valid JSON, no markdown:\n"
        '  {{"relevance": N, "correctness": N, "completeness": N, "conciseness": N, '
        '"issues": ["issue1", ...]}}\n'
    )

    def evaluate_semantic(
        self,
        prompt: str,
        response: str,
        agent=None,
        heuristic_quality: float = 1.0,
        config: dict | None = None,
    ) -> dict | None:
        """Use a cheap LLM as a quality judge.

        Only called when:
          1. ``semantic_eval_enabled`` is True in config
          2. ``heuristic_quality`` < ``semantic_eval_threshold`` (default 0.5)

        Returns ``{"quality": float, "issues": list, "breakdown": dict}`` or
        ``None`` when semantic eval is skipped / fails.
        """
        cfg = (config or {}).get("evaluation", {})
        if not cfg.get("semantic_eval_enabled", False):
            return None
        threshold = cfg.get("semantic_eval_threshold", 0.5)
        if heuristic_quality >= threshold:
            return None  # heuristic is good enough

        provider = self._get_eval_provider(agent)
        if not provider:
            return None

        eval_prompt = self._EVAL_PROMPT.format(
            task=prompt[:1500],
            response=response[:3000],
        )
        try:
            result = provider.chat(
                [{"role": "user", "content": eval_prompt}],
                stream=False,
            )
            text = result if isinstance(result, str) else "".join(result)
            scores = self._parse_eval_json(text)
            if not scores:
                return None

            dims = ["relevance", "correctness", "completeness", "conciseness"]
            raw = sum(scores.get(d, 5) for d in dims)
            semantic_q = raw / 40.0  # normalise to 0-1

            # Blend: 40% heuristic + 60% semantic
            blend_h = cfg.get("blend_heuristic", 0.4)
            blend_s = cfg.get("blend_semantic", 0.6)
            blended = blend_h * heuristic_quality + blend_s * semantic_q

            return {
                "quality": round(max(0.0, min(1.0, blended)), 4),
                "issues": scores.get("issues", []),
                "breakdown": {d: scores.get(d, 5) for d in dims},
            }
        except Exception:
            return None

    @staticmethod
    def _parse_eval_json(text: str) -> dict | None:
        """Best-effort extraction of the judge's JSON scores."""
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        m = re.search(r'\{[^{}]*"relevance"[^{}]*\}', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        return None

    @staticmethod
    def _get_eval_provider(agent):
        """Get the cheapest available provider for evaluation."""
        if not agent:
            return None
        from providers import get_provider
        providers_conf = getattr(agent, "config", {}).get("providers", {})
        for pname in ("grok", "copilot"):  # prefer cheaper grok-mini before expensive claude-sonnet
            if pname in providers_conf:
                try:
                    return get_provider(pname, providers_conf[pname])
                except Exception:
                    continue
        return getattr(agent, "provider", None)

    # ─── Task Classification ───

    TASK_PATTERNS = {
        # ── Cybersecurity fit-diagram specific categories (checked first) ──────────────
        # These are more specific than the broad categories below; a match here wins
        # because the scoring keeps the first (highest-match) key.

        # Run locally (Ollama-preferred) — fits on 4 GB VRAM
        "log_triage": r"log.?triage|triage.?log|parse.?log|log.?pars|classify.?(noise|alert)|syslog.?(alert|anomaly)|auth.?log|event.?log|log.?classif",
        "yara_sigma": r"yara|sigma.?rule|detection.?rule|ioc.?rule|write.?(yara|sigma)|generate.?rule|rule.?from.?ioc|indicator.?of.?compromise",
        "cve_summar": r"cve.?summar|explain.*advisory|score.*severity|cvss|vulnerability.?advisory|cve.?detail|patch.?note|nist.?nvd|\bcve\b|\bcve[-\s]\d{4}-\d+",
        "phishing": r"phish|spear.?phish|email.?header|mail.?header|classify.?email|suspicious.?email|email.?tone|link.?analysis|url.?triage",
        "traffic": r"pcap|packet.?capture|traffic.?summar|network.?traffic|wireshark|tcpdump|flag.?anomal|flow.?analys",

        # Offload to cloud — needs large context / world knowledge
        "malware_re": r"malware.?(re|reverse|analys)|reverse.?engineer.*malware|disassembl|decompil|binary.?analys|ida.?pro|ghidra|malware.?sample",
        "ti_synthesis": r"threat.?intel|ti.?report|apt.?group|threat.?actor|ioc.?correlation|multi.?source.?intel|threat.?landscape",
        "exploit_chain": r"exploit.?chain|multi.?step.?exploit|lateral.?movement.*exploit|attack.?chain|kill.?chain.*exploit|chained.?vuln",
        "ir_report": r"incident.?response.?report|ir.?report|post.?incident|executive.?summar.*incident|long.?form.?report|full.?pentest.?report",

        # ── Broad task categories (fallback when no specific match above) ─────────────
        "recon": r"recon|osint|footprint|subdomain|dns|whois|shodan|dorking|enum.*domain|searchsploit|exploitdb|exploit.?db|msfconsole|metasploit",
        "scan": r"nmap|scan|port|nikto|gobuster|dirb|enumerate|banner|service.?detect|enum4linux|masscan|rustscan",
        "exploit": r"exploit|shell|rce|reverse.?shell|payload|metasploit|buffer.?overflow|inject|sqli|xss|ssrf|lfi|rfi",
        "password": r"password|brute.?force|hydra|hashcat|john|crack|credential|wordlist",
        "privesc": r"priv.?esc|privilege|escalat|suid|sudo|linpeas|winpeas|lateral",
        "web": r"web.?app|burp|api|fuzz|idor|auth.?bypass|cookie|session|cors|csrf",
        "sysadmin": r"install|service|config|cron|firewall|iptables|user.?add|disk|\blog\b|monitor|process|uptime",
        "debug": r"debug|fix.?bug|bug.?fix|traceback|exception|stack.?trace|failing.?test|why.*(break|fail)|investigate.?error",
        "refactor": r"refactor|clean.?up.?code|restructure|rename.?function|rename.?class|extract.?method|improve.?code",
        "test": r"unit.?test|integration.?test|pytest|jest|vitest|mocha|write.?tests|test.?coverage|failing.?spec",
        "architecture": r"architecture|design.?pattern|codebase.?design|project.?structure|scaffold|build.?a(n)?|implement.?feature|add.?feature",
        "code": r"write.*(script|code|tool|program)|python|bash|ruby|javascript|typescript|react|flask|django|fastapi|html|css|app\.js|server\.py|function|class|method|automate|create.?tool|build.?app|generate.?code|implement",
        "analysis": r"analyz|explain|report|summar|what.?is|how.?does|tell.?me|describe",
    }

    def classify_task(self, prompt: str) -> str:
        """Classify a user prompt into a task type.

        "analysis" is a broad catch-all pattern — if any more-specific type
        also matches, prefer that over "analysis" to avoid misclassification.
        """
        prompt_lower = prompt.lower()
        scores = {}
        for task_type, pattern in self.TASK_PATTERNS.items():
            matches = len(re.findall(pattern, prompt_lower))
            if matches:
                scores[task_type] = matches
        if not scores:
            return "general"
        best = max(scores, key=scores.get)
        # Don't let the generic "analysis" regex override a more-specific match
        if best == "analysis":
            specific = {k: v for k, v in scores.items() if k != "analysis"}
            if specific:
                return max(specific, key=specific.get)
        return best

    # ─── Scoring Functions ───

    # Tasks that should contain code blocks in the response
    _CODE_TASKS = {"code", "exploit", "debug", "refactor", "test", "architecture",
                   "yara_sigma", "malware_re"}

    # Phrases that signal the LLM is refusing / hallucinating instead of acting
    _HALLUCINATION_MARKERS = [
        "as an ai", "i cannot access", "i don't have real-time",
        "i'm unable to", "i cannot assist", "i can't perform",
        "i don't have the ability", "in a hypothetical scenario",
        "as a language model", "i must emphasize",
    ]

    def _quality_score(self, prompt: str, response: str,
                       tool_calls: int, tool_successes: int, task_type: str) -> tuple[float, list[str]]:
        """Heuristic quality score based on response properties.

        Returns (score, issues) where *issues* is a list of human-readable
        strings explaining any deductions.
        """
        score = 0.5  # baseline
        issues: list[str] = []

        # ── Length: bell-curve scoring (peak at ideal_words) ──────────────
        words = len(response.split())
        ideal = 150 if task_type in self._CODE_TASKS else 400
        if words == 0:
            score -= 0.25
            issues.append("empty_response")
        else:
            # Gaussian-ish: score peaks at ideal, decays for shorter/longer
            ratio = (words - ideal) / max(ideal, 1)
            length_bonus = 0.20 * math.exp(-(ratio ** 2))  # raised 0.15→0.20 for better score resolution
            score += length_bonus
            if words < 15:
                score -= 0.15
                issues.append("response_too_short")

        # ── Tool usage signals competence for action tasks ────────────────
        action_tasks = {"recon", "scan", "exploit", "password", "privesc", "web",
                        "sysadmin", "code", "debug", "refactor", "test",
                        "architecture", "yara_sigma", "malware_re"}
        if task_type in action_tasks:
            if tool_calls > 0:
                score += 0.10
            if tool_successes > 0:
                score += 0.10
            if tool_calls > 0 and tool_successes == tool_calls:
                score += 0.05  # all tools succeeded
            if tool_calls == 0:
                score -= 0.10
                issues.append("action_task_no_tool_use")

        # ── Structured output (markdown, tables, code blocks) ─────────────
        if "```" in response:
            score += 0.03
        if "|" in response and "---" in response:
            score += 0.03
        if re.search(r"##?\s", response):
            score += 0.02

        # ── Task alignment: code tasks should have code ───────────────────
        if task_type in self._CODE_TASKS:
            if "```" not in response and "def " not in response and "function " not in response:
                score -= 0.08
                issues.append("code_task_missing_code")

        # ── Hallucination / refusal detector ──────────────────────────────
        resp_lower = response.lower()
        for marker in self._HALLUCINATION_MARKERS:
            if marker in resp_lower:
                score -= 0.12
                issues.append(f"hallucination_marker:{marker}")
                break  # one penalty is enough

        # ── Error indicators ──────────────────────────────────────────────
        error_patterns = r"\[LLM Error|\[Error|failed|timeout|refused"
        if re.search(error_patterns, response, re.IGNORECASE) and words < 40:
            score -= 0.15
            issues.append("error_in_short_response")

        return max(0.0, min(1.0, score)), issues

    def _latency_score(self, seconds: float) -> float:
        """Convert wall-clock seconds to a 0-1 score (higher = faster).
        
        < 2s  → 1.0
        2-5s  → 0.8-1.0
        5-15s → 0.5-0.8
        15-60s → 0.2-0.5
        > 60s → < 0.2
        """
        if seconds <= 2:
            return 1.0
        elif seconds <= 5:
            return 0.8 + 0.2 * (5 - seconds) / 3
        elif seconds <= 15:
            return 0.5 + 0.3 * (15 - seconds) / 10
        elif seconds <= 60:
            return 0.2 + 0.3 * (60 - seconds) / 45
        else:
            return max(0.05, 0.2 * (120 - seconds) / 120)

    def _cost_score(self, provider: str, model: str, response: str) -> float:
        """Estimate cost and convert to 0-1 (higher = cheaper).
        
        Based on approximate token count and model pricing.
        """
        if provider == "copilot":
            return self._copilot_cost_score(model)

        # Estimate tokens (~4 chars per token)
        est_tokens = len(response) / 4
        est_cost_1k = self._get_model_cost(provider, model)
        est_cost = est_cost_1k * (est_tokens / 1000)

        # Normalize: $0 → 1.0, $0.01 → ~0.7, $0.10 → ~0.2, $1.00 → ~0.05
        if est_cost <= 0:
            return 1.0
        # Sigmoid-ish curve
        return max(0.05, 1.0 / (1.0 + est_cost * 50))

    def _copilot_cost_score(self, model: str) -> float:
        """Score Copilot cost based on Pro premium-request multipliers, not USD/token."""
        mult = get_copilot_multiplier(model)
        if mult == 0:
            return 1.0
        if mult <= 0.33:
            return 0.9
        if mult <= 1.0:
            return 0.7
        if mult <= 3.0:
            return 0.35
        return 0.15

    def _get_model_cost(self, provider: str, model: str) -> float:
        """Look up rough cost per 1K tokens for a model."""
        # Try exact match first, then partial
        model_short = model.split("/")[-1] if "/" in model else model
        if model_short in MODEL_COST_PER_1K:
            return MODEL_COST_PER_1K[model_short]
        # Fuzzy fallback
        for key, cost in MODEL_COST_PER_1K.items():
            if key in model_short or model_short in key:
                return cost
        return 0.010  # default mid-range
