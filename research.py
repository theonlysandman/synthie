"""
research.py — Background business research for Synthie
=====================================================
Given a customer's website URL, fetch a few key pages, then use the Foundry
chat model (AGENT_MODEL / MODEL_DEPLOYMENT_NAME, e.g. gpt-4.1) to synthesize a
structured business profile: industry, products, customers & geography,
existing AI, and revenue/cost levers that hint at a first digital decision to
automate.

Results are cached on disk (research/<domain>.json) so a given site is only
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
from urllib.parse import urljoin, urlparse

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

# Pages we try to pull beyond the homepage, by link text / path hints.
_PAGE_HINTS = (
    "about", "product", "service", "solution", "industr", "what-we-do",
    "company", "platform", "customer", "ai", "technology", "overview",
)
_MAX_PAGES = 6
_MAX_CHARS_PER_PAGE = 6000
_FETCH_TIMEOUT = 15.0
_USER_AGENT = "SynthieResearch/1.0 (+business-discovery)"


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
# Web fetching
# ---------------------------------------------------------------------------
def _visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text[:_MAX_CHARS_PER_PAGE]


def _discover_links(base_url: str, html: str) -> list[str]:
    """Pick a handful of on-domain links that look informative."""
    soup = BeautifulSoup(html, "html.parser")
    base_host = domain_of(base_url)
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"].split("#")[0])
        if not href.startswith("http"):
            continue
        if domain_of(href) != base_host:
            continue
        if href in seen:
            continue
        seen.add(href)
        haystack = (href + " " + a.get_text(" ", strip=True)).lower()
        score = sum(1 for hint in _PAGE_HINTS if hint in haystack)
        if score > 0:
            scored.append((score, href))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [href for _, href in scored[: _MAX_PAGES - 1]]


async def _fetch_pages(url: str) -> list[dict[str, str]]:
    """Fetch the homepage plus a few informative internal pages."""
    pages: list[dict[str, str]] = []
    headers = {"User-Agent": _USER_AGENT}
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=_FETCH_TIMEOUT, headers=headers
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        home_html = resp.text
        pages.append({"url": str(resp.url), "text": _visible_text(home_html)})

        for link in _discover_links(str(resp.url), home_html):
            try:
                r = await client.get(link)
                r.raise_for_status()
                ctype = r.headers.get("content-type", "")
                if "html" not in ctype:
                    continue
                pages.append({"url": str(r.url), "text": _visible_text(r.text)})
            except Exception:  # noqa: BLE001
                continue
    return pages


# ---------------------------------------------------------------------------
# LLM analysis
# ---------------------------------------------------------------------------
_ANALYSIS_SYSTEM = """You are a B2B business analyst. Given raw text scraped from a company's website,
produce a concise, structured profile to help a seller find the first AI/digital decision worth
automating for this company. Distinguish FACT (clearly stated on the site) from INFERENCE (your
educated guess). Never invent specifics that aren't supported. Respond with JSON only."""

_ANALYSIS_INSTRUCTIONS = """From the website text below, fill in this JSON shape exactly:

{
  "company_name": "string",
  "one_liner": "what the company does, one sentence",
  "industry": "primary industry / sector",
  "products_services": ["key products or services"],
  "customers": "who their customers are (segments, B2B/B2C)",
  "geography": "where they and their customers operate",
  "business_model": "how they appear to make money",
  "existing_ai": "any AI/ML/automation products or initiatives mentioned, else 'none found'",
  "revenue_levers": ["where revenue could be grown"],
  "cost_levers": ["where costs likely sit / could be cut"],
  "data_signals": ["kinds of data this business probably has"],
  "first_decision_hypotheses": ["candidate first digital decisions to automate, outcome-first"],
  "inferences": ["items above that are inference rather than stated fact"],
  "confidence": "high | medium | low"
}

Keep arrays to 3-6 short items. Be specific to THIS company, not generic. JSON only, no prose."""


def _analyze(pages: list[dict[str, str]], url: str) -> dict[str, Any]:
    """Call the Foundry chat model to produce a structured profile."""
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

    corpus = "\n\n".join(f"### {p['url']}\n{p['text']}" for p in pages)
    corpus = corpus[:24000]

    completion = client.chat.completions.create(
        model=_ANALYSIS_MODEL,
        response_format={"type": "json_object"},
        temperature=0.2,
        messages=[
            {"role": "system", "content": _ANALYSIS_SYSTEM},
            {
                "role": "user",
                "content": f"Website: {url}\n\n{_ANALYSIS_INSTRUCTIONS}\n\n--- WEBSITE TEXT ---\n{corpus}",
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
    """Research a business by URL, using the on-disk cache unless force=True."""
    import asyncio

    clean_url = normalize_url(url)
    domain = domain_of(clean_url)

    if not force:
        cached = load_cached(domain)
        if cached:
            cached["cached"] = True
            return cached

    pages = await _fetch_pages(clean_url)
    if not pages:
        raise RuntimeError(f"Could not fetch any pages from {clean_url}")

    # The OpenAI client is synchronous — run it off the event loop.
    profile = await asyncio.to_thread(_analyze, pages, clean_url)

    record: dict[str, Any] = {
        "domain": domain,
        "url": clean_url,
        "researched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": [p["url"] for p in pages],
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

    src = record.get("url", "")
    return (
        "[BACKGROUND RESEARCH — reference only, the user did NOT say this. "
        f"Auto-gathered from {src}. Confirm rather than re-ask; mark inferences as inferences.]\n"
        + "\n".join(lines)
    )
