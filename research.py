"""
research.py — Background business research for Synthie
=====================================================
Given a customer's website domain, gather a few REAL search-result snippets about
the company (via DuckDuckGo — no API key, not blocked by the site's own WAF), then
use the Foundry chat model (AGENT_MODEL / MODEL_DEPLOYMENT_NAME, e.g. gpt-4.1) to
synthesize a structured business profile grounded in those snippets: industry,
products, customers & geography, existing AI, and revenue/cost levers that hint at
a first digital decision to automate.

We do NOT scrape the company's own website (many block automated access via
Cloudflare/WAFs). Instead we rely on already-indexed search snippets. When search
turns up little or nothing, the profile is marked low-confidence and framed as
unverified hypotheses to confirm with the customer — never asserted as fact.

Results are cached on disk (research/<domain>.json) so a given domain is only
researched once. Subsequent sessions reuse the cached profile instantly.

Used by server.py:
    profile = await research_business("https://example.com")
    profile = load_cached("example.com")            # None if not researched yet
    text = profile_to_prompt(profile)               # injectable context string
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
load_dotenv()

_REPO_ROOT = Path(__file__).parent
_CACHE_DIR = _REPO_ROOT / "research"
_CACHE_DIR.mkdir(exist_ok=True)

# The chat deployment used for analysis — reuse the agent brain (Responses /
# chat compatible), NOT the realtime voice model.
_ANALYSIS_MODEL = os.environ.get("AGENT_MODEL") or os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4.1")
_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")

# Search grounding (DuckDuckGo HTML endpoint — no key required).
_SEARCH_TIMEOUT = 12.0
_MAX_SNIPPETS = 8
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# Domain / cache helpers
# ---------------------------------------------------------------------------
def normalize_url(raw: str) -> str:
    """Return a clean absolute URL (adds https:// if the scheme is missing)."""
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Empty URL")
    if not re.match(r"^https?://", raw, re.IGNORECASE):
        raw = "https://" + raw
    return raw


def domain_of(raw: str) -> str:
    """Return a normalized registrable host, e.g. 'example.com' (no www)."""
    host = urlparse(normalize_url(raw)).netloc.lower()
    host = host.split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def _cache_path(domain: str) -> Path:
    safe = re.sub(r"[^a-z0-9._-]", "_", domain.lower())
    return _CACHE_DIR / f"{safe}.json"


def load_cached(domain: str) -> Optional[dict[str, Any]]:
    """Return the cached profile for a domain, or None if not researched yet."""
    path = _cache_path(domain)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _save_cache(domain: str, data: dict[str, Any]) -> None:
    _cache_path(domain).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Search grounding (DuckDuckGo — real indexed snippets, no key, not WAF-blocked)
# ---------------------------------------------------------------------------
async def _search_snippets(query: str) -> list[dict[str, str]]:
    """Return a few real search-result snippets for a query, or [] on failure."""
    out: list[dict[str, str]] = []
    try:
        async with httpx.AsyncClient(
            timeout=_SEARCH_TIMEOUT, headers=_BROWSER_HEADERS, follow_redirects=True
        ) as client:
            resp = await client.post(
                "https://html.duckduckgo.com/html/", data={"q": query}
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for res in soup.select(".result"):
                a = res.select_one("a.result__a")
                if not a:
                    continue
                snip = res.select_one(".result__snippet")
                out.append(
                    {
                        "title": a.get_text(" ", strip=True),
                        "snippet": snip.get_text(" ", strip=True) if snip else "",
                        "url": a.get("href", ""),
                    }
                )
                if len(out) >= _MAX_SNIPPETS:
                    break
    except Exception:  # noqa: BLE001 — search is best-effort; degrade gracefully
        return []
    return out


async def _gather_evidence(domain: str) -> list[dict[str, str]]:
    """Collect real snippets about the company from a couple of search queries."""
    seen: set[str] = set()
    evidence: list[dict[str, str]] = []
    # Query the domain itself, then the company's own indexed pages.
    for query in (domain, f"site:{domain}", f"{domain} company products customers"):
        for item in await _search_snippets(query):
            key = item.get("url") or item.get("title")
            if not key or key in seen:
                continue
            seen.add(key)
            evidence.append(item)
        if len(evidence) >= _MAX_SNIPPETS:
            break
    return evidence[:_MAX_SNIPPETS]


# ---------------------------------------------------------------------------
# LLM analysis (grounded in real search snippets)
# ---------------------------------------------------------------------------
_ANALYSIS_SYSTEM = """You are a B2B business analyst. You are given a company's website domain plus a
set of REAL search-result snippets about that company. Produce a concise, structured profile to
help a seller find the first AI/digital decision worth automating for this company.

Ground every claim in the provided snippets. Distinguish FACT (directly supported by a snippet)
from INFERENCE (a reasonable guess based on the snippets, domain, or typical companies in this
space). If the snippets are sparse, off-topic, or absent, DO NOT fall back on guesses about a
similarly named company — instead infer only cautiously from the domain name itself and set
confidence to "low". NEVER fabricate specific names, numbers, customers, or products that the
snippets do not support. Respond with JSON only."""

_ANALYSIS_INSTRUCTIONS = """Fill in this JSON shape exactly for the company at the given domain,
using the search snippets as your evidence:

{
  "company_name": "string",
  "one_liner": "what the company does, one sentence",
  "industry": "primary industry / sector",
  "products_services": ["key products or services"],
  "customers": "who their customers are (segments, B2B/B2C)",
  "geography": "where they and their customers operate",
  "business_model": "how they appear to make money",
  "existing_ai": "any AI/ML/automation products or initiatives mentioned, else 'none known'",
  "revenue_levers": ["where revenue could be grown"],
  "cost_levers": ["where costs likely sit / could be cut"],
  "data_signals": ["kinds of data this business probably has"],
  "first_decision_hypotheses": ["candidate first digital decisions to automate, outcome-first"],
  "inferences": ["items above that are inference rather than supported by a snippet"],
  "confidence": "high | medium | low"
}

Confidence rubric: "high" = multiple snippets clearly describe this exact company; "medium" = some
supporting snippets but gaps; "low" = little or no usable evidence (be honest — this is expected for
small or niche companies). Keep arrays to 3-6 short items. Be specific to THIS company where the
evidence allows, not generic. JSON only, no prose."""


def _analyze(domain: str, url: str, evidence: list[dict[str, str]]) -> dict[str, Any]:
    """Call the Foundry chat model to produce a structured profile grounded in snippets."""
    from azure.identity import AzureCliCredential, get_bearer_token_provider
    from openai import AzureOpenAI

    endpoint = (
        os.environ.get("VOICELIVE_ENDPOINT")
        or os.environ.get("AZURE_OPENAI_ENDPOINT")
        or ""
    ).rstrip("/") + "/"

    token_provider = get_bearer_token_provider(
        AzureCliCredential(), "https://cognitiveservices.azure.com/.default"
    )
    client = AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version=_OPENAI_API_VERSION,
    )

    if evidence:
        ev_lines = []
        for i, e in enumerate(evidence, 1):
            ev_lines.append(
                f"[{i}] {e.get('title','')}\n{e.get('snippet','')}\n({e.get('url','')})"
            )
        evidence_block = "\n\n".join(ev_lines)
    else:
        evidence_block = "(No usable search results were found for this domain.)"

    completion = client.chat.completions.create(
        model=_ANALYSIS_MODEL,
        response_format={"type": "json_object"},
        temperature=0.2,
        messages=[
            {"role": "system", "content": _ANALYSIS_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Company domain: {domain}\nWebsite: {url}\n\n{_ANALYSIS_INSTRUCTIONS}\n\n"
                    f"--- SEARCH SNIPPETS ---\n{evidence_block}"
                ),
            },
        ],
    )
    raw = completion.choices[0].message.content or "{}"
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return {"_parse_error": True, "raw": raw}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def research_business(url: str, *, force: bool = False) -> dict[str, Any]:
    """Research a business by domain, using the on-disk cache unless force=True."""
    import asyncio

    clean_url = normalize_url(url)
    domain = domain_of(clean_url)

    if not force:
        cached = load_cached(domain)
        if cached:
            cached["cached"] = True
            return cached

    # 1) Gather real evidence from search (best-effort).
    evidence = await _gather_evidence(domain)

    # 2) Analyze, grounded in that evidence. OpenAI client is sync — off-thread it.
    profile = await asyncio.to_thread(_analyze, domain, clean_url, evidence)

    record: dict[str, Any] = {
        "domain": domain,
        "url": clean_url,
        "researched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "method": "search-grounded",
        "grounded": bool(evidence),
        "sources": [e.get("url", "") for e in evidence if e.get("url")],
        "profile": profile,
        "cached": False,
    }
    _save_cache(domain, record)
    return record


def profile_to_prompt(record: dict[str, Any]) -> str:
    """Render a cached research record into context text for the voice agent."""
    if not record:
        return ""
    p = record.get("profile", {}) or {}
    lines: list[str] = []

    def add(label: str, value: Any) -> None:
        if not value:
            return
        if isinstance(value, list):
            value = "; ".join(str(v) for v in value)
        lines.append(f"- {label}: {value}")

    add("Company", p.get("company_name"))
    add("What they do", p.get("one_liner"))
    add("Industry", p.get("industry"))
    add("Products / services", p.get("products_services"))
    add("Customers", p.get("customers"))
    add("Geography", p.get("geography"))
    add("Business model", p.get("business_model"))
    add("Existing AI", p.get("existing_ai"))
    add("Revenue levers", p.get("revenue_levers"))
    add("Cost levers", p.get("cost_levers"))
    add("Likely data", p.get("data_signals"))
    add("Candidate first decisions", p.get("first_decision_hypotheses"))
    add("Treat as inference (not confirmed)", p.get("inferences"))

    if not lines:
        return ""

    confidence = str(p.get("confidence", "") or "").lower()
    grounded = record.get("grounded", False)
    src = record.get("url", "")

    if confidence == "high" and grounded:
        header = (
            "[BACKGROUND RESEARCH — reference only, the user did NOT say this. "
            f"Gathered from public search results about {src} and judged HIGH confidence. "
            "Confirm key points naturally rather than re-asking from scratch; still treat "
            "anything marked inference as unconfirmed.]"
        )
    elif confidence == "medium":
        header = (
            "[BACKGROUND RESEARCH — reference only, the user did NOT say this. "
            f"Gathered from public search results about {src} but only MEDIUM confidence. "
            "Use it to orient yourself, but LEAD by confirming (e.g. 'Looks like you're in X — "
            "is that right?') instead of stating it as fact.]"
        )
    else:  # low confidence or ungrounded
        header = (
            "[BACKGROUND RESEARCH — LOW CONFIDENCE / UNVERIFIED. The user did NOT say this and "
            f"public search turned up little about {src}. Do NOT assert any of this as fact. "
            "Treat every line as a hypothesis to check, and open by asking the customer to "
            "describe their business in their own words.]"
        )

    return header + "\n" + "\n".join(lines)
