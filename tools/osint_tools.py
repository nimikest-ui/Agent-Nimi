"""
OSINT Tools — Phase 14
─────────────────────
Open-source intelligence gathering:  web search, CVE lookup, GitHub search,
Shodan host info, and WHOIS.  All tools degrade gracefully when API keys or
network access are unavailable.
"""
from __future__ import annotations

import json
import re
import socket
import subprocess
from typing import Any
from urllib.parse import quote_plus

import requests

from tools.registry import tool

# ── Shared helpers ─────────────────────────────────────────────────────────────

_DEFAULT_TIMEOUT = 15
_USER_AGENT = "AgentNimi/1.0 (security research; authorized pentest)"


def _get(url: str, params: dict | None = None, headers: dict | None = None, timeout: int = _DEFAULT_TIMEOUT) -> requests.Response:
    h = {"User-Agent": _USER_AGENT}
    if headers:
        h.update(headers)
    return requests.get(url, params=params, headers=h, timeout=timeout)


# ── web_search ────────────────────────────────────────────────────────────────

@tool(
    name="web_search",
    description=(
        "Search the web using DuckDuckGo and return the top results with titles, "
        "URLs, and snippets. No API key required. Best for general OSINT, "
        "CVE research, tool documentation, and target reconnaissance."
    ),
    manifest={
        "category": "osint",
        "action_class": "read_only",
        "capabilities": ["web_search", "osint"],
        "trust_tier": "tier_1",
        "provider_affinity": "any",
    },
)
def web_search(query: str, max_results: int = 8) -> str:
    """DuckDuckGo instant-answer API search (zero-click JSON endpoint)."""
    try:
        # Try DuckDuckGo Instant Answer API first
        resp = _get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
        )
        resp.raise_for_status()
        data = resp.json()

        results: list[str] = []

        # Abstract (best single answer)
        if data.get("AbstractText"):
            source = data.get("AbstractSource", "")
            url = data.get("AbstractURL", "")
            results.append(f"[ANSWER] {data['AbstractText']}\nSource: {source} — {url}")

        # Related topics
        for item in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(item, dict) and item.get("Text"):
                topic_url = item.get("FirstURL", "")
                results.append(f"• {item['Text']}\n  {topic_url}")

        # Results section
        for item in data.get("Results", [])[:max_results]:
            if isinstance(item, dict) and item.get("Text"):
                url = item.get("FirstURL", "")
                results.append(f"• {item['Text']}\n  {url}")

        if results:
            return f"Web search: '{query}'\n\n" + "\n\n".join(results[:max_results])

        # Fallback: DuckDuckGo HTML scrape
        return _ddg_html_search(query, max_results)

    except Exception as e:
        # Last-resort: try the HTML endpoint
        try:
            return _ddg_html_search(query, max_results)
        except Exception:
            return f"[web_search error] {e}"


def _ddg_html_search(query: str, max_results: int) -> str:
    """Scrape DuckDuckGo HTML for web results."""
    resp = _get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers={"Accept": "text/html"},
    )
    resp.raise_for_status()
    # Extract result snippets via simple regex (avoids BeautifulSoup dependency)
    snippets = re.findall(
        r'class="result__snippet"[^>]*>(.*?)</a>',
        resp.text,
        re.DOTALL,
    )
    urls = re.findall(r'class="result__url"[^>]*>(.*?)</a>', resp.text, re.DOTALL)
    titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', resp.text, re.DOTALL)

    def strip_tags(s: str) -> str:
        return re.sub(r"<[^>]+>", "", s).strip()

    lines = [f"Web search: '{query}'\n"]
    for i, (t, u, s) in enumerate(zip(titles, urls, snippets)):
        if i >= max_results:
            break
        lines.append(f"[{i+1}] {strip_tags(t)}\n    {strip_tags(u)}\n    {strip_tags(s)}")
    return "\n\n".join(lines) if len(lines) > 1 else f"No results found for '{query}'"


# ── cve_lookup ────────────────────────────────────────────────────────────────

@tool(
    name="cve_lookup",
    description=(
        "Look up a CVE by ID (e.g. CVE-2021-44228) or search for CVEs by keyword "
        "using the NIST NVD API. Returns severity, CVSS score, vector, description, "
        "and references. No API key required."
    ),
    manifest={
        "category": "osint",
        "action_class": "read_only",
        "capabilities": ["cve_research", "osint", "vulnerability_analysis"],
        "trust_tier": "tier_1",
        "provider_affinity": "any",
    },
)
def cve_lookup(cve_id: str = "", keyword: str = "", max_results: int = 5) -> str:
    """Query the NIST NVD REST API v2 for CVE data."""
    try:
        params: dict[str, Any] = {"resultsPerPage": min(max_results, 20)}

        if cve_id:
            cve_id = cve_id.upper().strip()
            if not re.match(r"CVE-\d{4}-\d{4,}", cve_id):
                return f"Invalid CVE ID format: '{cve_id}'. Use CVE-YYYY-NNNNN."
            params["cveId"] = cve_id
        elif keyword:
            params["keywordSearch"] = keyword
        else:
            return "Provide cve_id or keyword."

        resp = _get("https://services.nvd.nist.gov/rest/json/cves/2.0", params=params)
        resp.raise_for_status()
        data = resp.json()

        vulns = data.get("vulnerabilities", [])
        if not vulns:
            return f"No CVEs found for {'CVE ID ' + cve_id if cve_id else 'keyword: ' + keyword}"

        output_parts: list[str] = []
        for entry in vulns[:max_results]:
            cve = entry.get("cve", {})
            cid = cve.get("id", "Unknown")
            desc_list = cve.get("descriptions", [])
            desc = next((d["value"] for d in desc_list if d.get("lang") == "en"), "No description")

            # CVSS v3 score
            cvss_v3 = ""
            metrics = cve.get("metrics", {})
            for key in ("cvssMetricV31", "cvssMetricV30"):
                if key in metrics and metrics[key]:
                    m = metrics[key][0].get("cvssData", {})
                    score = m.get("baseScore", "?")
                    severity = m.get("baseSeverity", "?")
                    vector = m.get("vectorString", "")
                    cvss_v3 = f"CVSS {score} ({severity}) — {vector}"
                    break

            # References
            refs = [r.get("url", "") for r in cve.get("references", [])[:3]]
            ref_str = "\n    ".join(refs) if refs else "None"

            published = cve.get("published", "")[:10]
            output_parts.append(
                f"{'='*60}\n"
                f"{cid}  [{published}]\n"
                f"CVSS: {cvss_v3 or 'N/A'}\n"
                f"Description: {desc[:500]}\n"
                f"References:\n    {ref_str}"
            )

        return "\n".join(output_parts)

    except requests.Timeout:
        return "[cve_lookup] Request timed out (NVD API slow). Try again."
    except Exception as e:
        return f"[cve_lookup error] {e}"


# ── github_search ─────────────────────────────────────────────────────────────

@tool(
    name="github_search",
    description=(
        "Search GitHub for repositories, code snippets, or security tools. "
        "Useful for finding PoC exploits, security tools, and target source code. "
        "Uses GitHub Search API (no key needed, rate limited to 10 req/min unauthenticated)."
    ),
    manifest={
        "category": "osint",
        "action_class": "read_only",
        "capabilities": ["github_search", "code_search", "osint"],
        "trust_tier": "tier_1",
        "provider_affinity": "any",
    },
)
def github_search(query: str, search_type: str = "repositories", max_results: int = 6) -> str:
    """Search GitHub repositories, code, or issues."""
    valid_types = {"repositories", "code", "issues", "commits", "topics"}
    if search_type not in valid_types:
        search_type = "repositories"

    try:
        resp = _get(
            f"https://api.github.com/search/{search_type}",
            params={"q": query, "per_page": min(max_results, 30), "sort": "stars", "order": "desc"},
            headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        total = data.get("total_count", 0)

        if not items:
            return f"No {search_type} found for '{query}'"

        lines = [f"GitHub search ({search_type}): '{query}'  —  {total} total results\n"]
        for item in items[:max_results]:
            if search_type == "repositories":
                name = item.get("full_name", "Unknown")
                desc = item.get("description") or ""
                stars = item.get("stargazers_count", 0)
                lang = item.get("language") or "Unknown"
                url = item.get("html_url", "")
                lines.append(f"★ {stars:,}  [{lang}]  {name}\n  {desc[:120]}\n  {url}")
            elif search_type == "code":
                repo = item.get("repository", {}).get("full_name", "?")
                path = item.get("path", "?")
                url = item.get("html_url", "")
                lines.append(f"• {repo}/{path}\n  {url}")
            else:
                title = item.get("title", item.get("name", str(item.get("sha", ""))[:12]))
                url = item.get("html_url", "")
                lines.append(f"• {title}\n  {url}")

        return "\n\n".join(lines)

    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            return "[github_search] Rate limited. Unauthenticated GitHub API allows 10 req/min. Set github_token in config."
        return f"[github_search error] {e}"
    except Exception as e:
        return f"[github_search error] {e}"


# ── shodan_host ───────────────────────────────────────────────────────────────

@tool(
    name="shodan_host",
    description=(
        "Query Shodan for port/service/banner data about a host IP or hostname. "
        "Requires SHODAN_API_KEY in config (free API key at shodan.io). "
        "Returns open ports, services, banners, and known vulns if available."
    ),
    manifest={
        "category": "osint",
        "action_class": "read_only",
        "capabilities": ["shodan", "port_scan", "osint", "banner_grabbing"],
        "trust_tier": "tier_1",
        "provider_affinity": "any",
    },
)
def shodan_host(host: str, config: dict | None = None) -> str:
    """Query Shodan host info API."""
    # Resolve hostname → IP if needed
    ip = host.strip()
    if not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip):
        try:
            ip = socket.gethostbyname(host)
        except socket.gaierror:
            return f"[shodan_host] Cannot resolve hostname: {host}"

    api_key = (config or {}).get("shodan", {}).get("api_key", "")
    if not api_key:
        import os
        api_key = os.environ.get("SHODAN_API_KEY", "")
    if not api_key:
        return (
            "[shodan_host] No Shodan API key configured. "
            "Add shodan.api_key to config or set SHODAN_API_KEY environment variable. "
            "Free key available at https://account.shodan.io/"
        )

    try:
        resp = _get(
            f"https://api.shodan.io/shodan/host/{ip}",
            params={"key": api_key},
        )
        resp.raise_for_status()
        data = resp.json()

        parts = [f"Shodan: {ip}  (resolved from '{host}')"] if ip != host else [f"Shodan: {ip}"]
        parts.append(f"Organization : {data.get('org', 'N/A')}")
        parts.append(f"ISP          : {data.get('isp', 'N/A')}")
        parts.append(f"Country      : {data.get('country_name', 'N/A')}")
        parts.append(f"OS           : {data.get('os', 'Unknown')}")
        parts.append(f"Last updated : {data.get('last_update', 'N/A')}")

        hostnames = data.get("hostnames", [])
        if hostnames:
            parts.append(f"Hostnames    : {', '.join(hostnames[:10])}")

        ports = data.get("ports", [])
        parts.append(f"Open ports   : {', '.join(str(p) for p in sorted(ports))}" if ports else "Open ports   : None")

        vulns = data.get("vulns", [])
        if vulns:
            parts.append(f"Known vulns  : {', '.join(sorted(vulns)[:15])}")

        # Service banners
        banners = data.get("data", [])
        if banners:
            parts.append("\n--- Service Banners ---")
            for svc in banners[:8]:
                port = svc.get("port", "?")
                transport = svc.get("transport", "tcp")
                product = svc.get("product", "")
                version = svc.get("version", "")
                banner = svc.get("data", "").strip()[:200].replace("\n", " ")
                service_line = f"  :{port}/{transport}"
                if product:
                    service_line += f"  {product}"
                if version:
                    service_line += f" {version}"
                if banner:
                    service_line += f"\n    {banner}"
                parts.append(service_line)

        return "\n".join(parts)

    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            return "[shodan_host] Invalid API key."
        if e.response is not None and e.response.status_code == 404:
            return f"[shodan_host] No info for {ip} — not in Shodan index."
        return f"[shodan_host error] {e}"
    except Exception as e:
        return f"[shodan_host error] {e}"


# ── whois_lookup ──────────────────────────────────────────────────────────────

@tool(
    name="whois_lookup",
    description=(
        "Run a WHOIS lookup for a domain or IP address to get registration, "
        "ownership, and contact info. Uses system 'whois' command — available on Kali."
    ),
    manifest={
        "category": "osint",
        "action_class": "read_only",
        "capabilities": ["whois", "domain_recon", "osint"],
        "trust_tier": "tier_1",
        "provider_affinity": "any",
    },
)
def whois_lookup(target: str, max_lines: int = 60) -> str:
    """Run system whois and return structured output."""
    target = target.strip().rstrip("./")
    if not target:
        return "No target specified."

    try:
        result = subprocess.run(
            ["whois", target],
            capture_output=True,
            text=True,
            timeout=20,
        )
        output = (result.stdout or "").strip()
        err = (result.stderr or "").strip()

        if not output and err:
            return f"[whois error] {err}"
        if not output:
            return f"No WHOIS data returned for {target}"

        # Filter out comments and empty lines, limit output
        lines = [l for l in output.splitlines() if l.strip() and not l.strip().startswith("%")]
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines.append(f"... [{len(output.splitlines()) - max_lines} more lines truncated]")

        return f"WHOIS: {target}\n\n" + "\n".join(lines)

    except FileNotFoundError:
        # whois not installed — try RDAP as fallback
        return _rdap_lookup(target)
    except subprocess.TimeoutExpired:
        return f"[whois_lookup] Timed out querying WHOIS for {target}"
    except Exception as e:
        return f"[whois_lookup error] {e}"


def _rdap_lookup(target: str) -> str:
    """RDAP fallback when whois binary not available."""
    try:
        # Try IANA RDAP
        # For domains: rdap.org/domain, for IPs: rdap.org/ip
        is_ip = bool(re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", target))
        url = f"https://rdap.org/{'ip' if is_ip else 'domain'}/{target}"
        resp = _get(url)
        resp.raise_for_status()
        data = resp.json()

        parts = [f"RDAP lookup: {target}"]
        if "name" in data:
            parts.append(f"Name: {data['name']}")
        for notice in data.get("notices", [])[:2]:
            title = notice.get("title", "")
            desc = " ".join(notice.get("description", []))[:200]
            if title:
                parts.append(f"{title}: {desc}")
        vcard = data.get("vcardArray", [])
        if vcard and len(vcard) > 1:
            for entry in vcard[1][:10]:
                if isinstance(entry, list) and len(entry) >= 4:
                    key, _, _, val = entry[:4]
                    if val and key not in ("version",):
                        parts.append(f"{key}: {val}")
        return "\n".join(parts)
    except Exception as e:
        return f"[whois_lookup] whois binary not found and RDAP fallback failed: {e}"
