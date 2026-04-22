"""
Logo search logic across multiple sources:
  1. Simple Icons  — SVG, great for tech/popular brands
  2. World Vector Logo CDN — SVG, broad catalog
  3. Clearbit Logo API — PNG/transparent, domain-based
  4. Company website scrape — direct SVG/PNG extraction
"""

from __future__ import annotations

import re
import requests
from typing import Optional
from urllib.parse import urljoin, urlparse

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
TIMEOUT = 8

# ── Slug helpers ──────────────────────────────────────────────────────────────

def _simple_slug(name: str) -> str:
    """Simple Icons slug: lowercase, alphanumeric only."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _hyphen_slug(name: str) -> str:
    """Hyphenated slug: lowercase, spaces/specials → hyphens."""
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def _guess_domains(query: str) -> list[str]:
    bases = {_simple_slug(query), _hyphen_slug(query)}
    tlds = [".com", ".io", ".co", ".ai", ".net", ".org"]
    domains = []
    for base in sorted(bases):
        if base:
            for tld in tlds:
                domains.append(base + tld)
    return domains


# ── Source 1: Simple Icons ────────────────────────────────────────────────────

_SIMPLE_ICONS_JSON = (
    "https://raw.githubusercontent.com/simple-icons/simple-icons"
    "/develop/_data/simple-icons.json"
)
_SIMPLE_ICONS_CDN = "https://cdn.simpleicons.org/{slug}"

def _fetch_svg(url: str) -> Optional[bytes]:
    try:
        r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
        if r.status_code == 200 and len(r.content) > 80 and b"<svg" in r.content[:2000]:
            return r.content
    except Exception:
        pass
    return None


def search_simple_icons(query: str) -> list[dict]:
    results = []

    # Fuzzy match against the full icon dataset
    try:
        r = requests.get(_SIMPLE_ICONS_JSON, timeout=10, headers=HEADERS)
        if r.status_code == 200:
            icons = r.json().get("icons", [])
            q = query.lower().strip()
            ranked = []
            for icon in icons:
                title = icon.get("title", "")
                t = title.lower()
                if t == q:
                    ranked.insert(0, (0, icon))
                elif q in t or t in q:
                    ranked.append((1, icon))
            for _, icon in ranked[:5]:
                slug = icon.get("slug") or _simple_slug(icon["title"])
                url = _SIMPLE_ICONS_CDN.format(slug=slug)
                content = _fetch_svg(url)
                if content:
                    results.append({
                        "name": icon["title"],
                        "url": url,
                        "format": "svg",
                        "source": "Simple Icons",
                        "content": content,
                    })
    except Exception:
        pass

    # Direct slug guess as fallback
    if not results:
        for slug in (_simple_slug(query), _hyphen_slug(query)):
            if slug:
                url = _SIMPLE_ICONS_CDN.format(slug=slug)
                content = _fetch_svg(url)
                if content:
                    results.append({
                        "name": query,
                        "url": url,
                        "format": "svg",
                        "source": "Simple Icons",
                        "content": content,
                    })
                    break

    return results


# ── Source 2: World Vector Logo CDN ──────────────────────────────────────────

_WVL_CDN = "https://cdn.worldvectorlogo.com/logos/{slug}.svg"

def search_worldvectorlogo(query: str) -> list[dict]:
    candidates = list({
        _hyphen_slug(query),
        _simple_slug(query),
        # Try removing common suffixes
        _hyphen_slug(re.sub(r"\b(inc|llc|ltd|corp|co)\b", "", query, flags=re.I).strip()),
    })
    for candidate in candidates:
        if not candidate:
            continue
        url = _WVL_CDN.format(slug=candidate)
        content = _fetch_svg(url)
        if content:
            return [{
                "name": query,
                "url": url,
                "format": "svg",
                "source": "World Vector Logo",
                "content": content,
            }]
    return []


# ── Source 3: Clearbit Logo API ───────────────────────────────────────────────

def search_clearbit(query: str, domain: Optional[str] = None) -> list[dict]:
    domains = [domain] if domain else _guess_domains(query)[:6]
    for d in domains:
        try:
            url = f"https://logo.clearbit.com/{d}"
            r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
            if r.status_code == 200 and len(r.content) > 300:
                ct = r.headers.get("content-type", "")
                fmt = "svg" if "svg" in ct else "png"
                return [{
                    "name": f"{query} ({d})",
                    "url": url,
                    "format": fmt,
                    "source": "Clearbit",
                    "content": r.content,
                }]
        except Exception:
            continue
    return []


# ── Source 4: Website scraping ────────────────────────────────────────────────

def search_website(website_url: str, query: str = "") -> list[dict]:
    from bs4 import BeautifulSoup

    results = []
    try:
        r = requests.get(website_url, timeout=10, headers=HEADERS)
        if r.status_code != 200:
            return results

        soup = BeautifulSoup(r.text, "lxml")
        parsed = urlparse(website_url)
        base = f"{parsed.scheme}://{parsed.netloc}"

        # <img> tags that look like logos
        for img in soup.find_all("img"):
            src = img.get("src", "")
            alt = img.get("alt", "").lower()
            cls = " ".join(img.get("class", [])).lower()
            id_ = img.get("id", "").lower()

            is_logo = any("logo" in x for x in [src.lower(), alt, cls, id_]) or \
                      any("brand" in x for x in [cls, id_])
            if not src or not is_logo:
                continue

            full_url = src if src.startswith("http") else urljoin(base, src)
            ext = full_url.split("?")[0].rsplit(".", 1)[-1].lower()
            if ext not in ("svg", "png", "webp"):
                continue

            try:
                ir = requests.get(full_url, timeout=TIMEOUT, headers=HEADERS)
                if ir.status_code == 200 and len(ir.content) > 100:
                    ct = ir.headers.get("content-type", "")
                    fmt = "svg" if (ext == "svg" or "svg" in ct) else "png"
                    results.append({
                        "name": f"Logo – {parsed.netloc}",
                        "url": full_url,
                        "format": fmt,
                        "source": "Company Website",
                        "content": ir.content,
                    })
            except Exception:
                pass

        # <link rel="icon"> SVG favicons
        for link in soup.find_all("link", rel=True):
            rels = [x.lower() for x in link.get("rel", [])]
            href = link.get("href", "")
            if not href:
                continue
            if any(r in rels for r in ("icon", "apple-touch-icon")) and href.endswith(".svg"):
                full_url = href if href.startswith("http") else urljoin(base, href)
                content = _fetch_svg(full_url)
                if content:
                    results.append({
                        "name": f"SVG icon – {parsed.netloc}",
                        "url": full_url,
                        "format": "svg",
                        "source": "Company Website (favicon)",
                        "content": content,
                    })

    except Exception:
        pass

    # Also try Clearbit with the real domain
    domain = urlparse(website_url).netloc.lstrip("www.")
    results.extend(search_clearbit(query or domain, domain=domain))

    return results


# ── Main entry point ──────────────────────────────────────────────────────────

def find_logos(query: str, website_url: Optional[str] = None) -> list[dict]:
    """Search all sources and return deduplicated logo list."""
    results: list[dict] = []

    results.extend(search_simple_icons(query))
    results.extend(search_worldvectorlogo(query))
    results.extend(search_clearbit(query))

    if website_url:
        results.extend(search_website(website_url, query=query))

    # Deduplicate by URL
    seen: set[str] = set()
    unique: list[dict] = []
    for logo in results:
        if logo["url"] not in seen:
            seen.add(logo["url"])
            unique.append(logo)

    return unique
