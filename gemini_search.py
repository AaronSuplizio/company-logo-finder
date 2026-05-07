"""
Optional Gemini-powered logo search fallback.
Uses gemini-1.5-flash (free tier) to identify a company's primary domain
and any known SVG logo URLs, then validates each with a real HTTP fetch.
"""

from __future__ import annotations

import json
import re

from google import genai

from logo_finder import (
    _fetch_svg,
    normalize_url,
    search_clearbit,
    search_simple_icons,
    search_website,
    search_wikimedia_commons,
)

_PROMPT = """You are helping find an official company logo SVG file.
Company: "{query}"

Reply with JSON only — no explanation, no markdown fences:
{{
  "official_name": "exact current brand name used in their logo",
  "former_names": ["any previous brand names, e.g. if they rebranded"],
  "domain": "primary website domain, e.g. stripe.com",
  "svg_urls": ["direct URL to an SVG logo file if you are highly confident it exists"]
}}

Rules:
- svg_urls must be real, publicly accessible URLs you are confident about.
- Leave svg_urls as an empty array if you are not certain.
- Do not invent URLs.
- former_names is important — many companies rebrand (e.g. Square → Block, Facebook → Meta).
"""


def find_logo_with_gemini(query: str, api_key: str) -> list[dict]:
    """Ask Gemini for domain + SVG URLs, validate each, return logo dicts."""
    client = genai.Client(api_key=api_key)

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=_PROMPT.format(query=query),
        )
        text = response.text or ""
    except Exception as exc:
        raise RuntimeError(f"Gemini API error: {exc}") from exc

    # Extract the first JSON object from the response
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return []

    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return []

    official_name: str = data.get("official_name") or query
    former_names: list[str] = data.get("former_names") or []
    domain: str = (data.get("domain") or "").strip().lower().removeprefix("www.")
    svg_urls: list[str] = data.get("svg_urls") or []

    results: list[dict] = []
    seen: set[str] = set()

    def _add(logo: dict) -> None:
        if logo["url"] not in seen:
            seen.add(logo["url"])
            results.append(logo)

    # Try direct SVG URLs Gemini suggested
    for url in svg_urls[:3]:
        url = url.strip()
        if not url:
            continue
        content = _fetch_svg(url)
        if content:
            _add({"name": official_name, "url": url, "format": "svg",
                  "source": "Gemini", "content": content})

    # Use Gemini's domain for targeted Clearbit + website scrape
    if domain:
        for logo in search_clearbit(official_name, domain=domain):
            _add(logo)
        for logo in search_website(normalize_url(domain), query=official_name):
            _add(logo)

    # Retry all name-based sources with official name and any former names
    from logo_finder import search_worldvectorlogo
    for name in [official_name] + former_names:
        if name.lower() != query.lower():
            for logo in search_simple_icons(name):
                _add(logo)
            for logo in search_worldvectorlogo(name):
                _add(logo)
        for logo in search_wikimedia_commons(name):
            _add(logo)

    return results
