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
    tlds = [".com", ".io", ".co", ".ai", ".net", ".org", ".xyz", ".app", ".dev"]
    domains = []
    for base in sorted(bases):
        if base:
            for tld in tlds:
                domains.append(base + tld)
    return domains


# ── Source 1: Simple Icons ────────────────────────────────────────────────────

# JSON is now a bare array: [{title, hex, slug?, ...}, ...]
_SIMPLE_ICONS_JSON = (
    "https://raw.githubusercontent.com/simple-icons/simple-icons"
    "/develop/data/simple-icons.json"
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

    try:
        r = requests.get(_SIMPLE_ICONS_JSON, timeout=10, headers=HEADERS)
        if r.status_code == 200:
            data = r.json()
            # Handle both old {"icons": [...]} and new bare-array formats
            icons = data if isinstance(data, list) else data.get("icons", [])
            q = query.lower().strip()
            ranked = []
            for icon in icons:
                title = icon.get("title", "")
                t = title.lower()
                if t == q:
                    ranked.insert(0, (0, icon))
                # Substring match only when both sides are substantial (≥4 chars)
                # to avoid short titles like "C" or "R" matching inside longer queries
                elif len(t) >= 4 and len(q) >= 4 and (q in t or t in q):
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
    base_candidates = list(dict.fromkeys(filter(None, [
        _hyphen_slug(query),
        _simple_slug(query),
        _hyphen_slug(re.sub(r"\b(inc|llc|ltd|corp|co)\b", "", query, flags=re.I).strip()),
    ])))

    # For each base slug, try plain then numbered variants (-1 through -5)
    # WVL uses numbered variants for logos with multiple versions
    slugs_to_try = []
    for base in base_candidates:
        slugs_to_try.append(base)
        for n in range(1, 6):
            slugs_to_try.append(f"{base}-{n}")

    results = []
    for slug in slugs_to_try:
        url = _WVL_CDN.format(slug=slug)
        content = _fetch_svg(url)
        if content:
            results.append({
                "name": query,
                "url": url,
                "format": "svg",
                "source": "World Vector Logo",
                "content": content,
            })
    # Reverse so higher-numbered (newer) variants appear first
    results.reverse()
    return results


# ── Source 3: Wikipedia article logos ────────────────────────────────────────

_WIKI_API = "https://en.wikipedia.org/w/api.php"
_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_WIKI_HEADERS = {**HEADERS, "User-Agent": "CompanyLogoFinder/1.0 (contact@example.com)"}

def search_wikimedia(query: str) -> list[dict]:
    results = []
    try:
        # Step 1: find the Wikipedia article title
        r = requests.get(_WIKI_API, params={
            "action": "query", "list": "search", "srsearch": query,
            "format": "json", "srlimit": 1,
        }, timeout=8, headers=_WIKI_HEADERS)
        hits = r.json().get("query", {}).get("search", [])
        if not hits:
            return results
        article_title = hits[0]["title"]

        # Step 2: get all images used in the article
        r2 = requests.get(_WIKI_API, params={
            "action": "parse", "page": article_title,
            "prop": "images", "format": "json",
        }, timeout=8, headers=_WIKI_HEADERS)
        images = r2.json().get("parse", {}).get("images", [])

        # Keep SVGs that contain "logo" and belong to the company (not Wiki system files)
        system = {"commons-logo", "wikinews-logo", "wikiquote-logo", "wikibooks-logo",
                  "wikiversity-logo", "wiktionary-logo", "wikivoyage-logo"}
        q_slug = re.sub(r"[^a-z0-9]", "", query.lower())
        logo_svgs = [
            img for img in images
            if img.lower().endswith(".svg")
            and "logo" in img.lower()
            and img.lower().replace("-", "").replace("_", "").replace(" ", "").split(".")[0] not in system
        ]

        if not logo_svgs:
            return results

        # Step 3: rank — prefer most recent year, then no year, skip "Historical"
        def _svg_rank(name: str):
            n = name.lower()
            if "historical" in n or "wordmark" in n:
                return (1, 0)
            years = re.findall(r"\b(19|20)\d{2}\b", name)
            return (0, -int(years[-1])) if years else (0, 1)

        logo_svgs.sort(key=_svg_rank)

        # Step 4: fetch URLs for top candidates
        file_titles = [f"File:{img}" for img in logo_svgs[:4]]
        r3 = requests.get(_WIKI_API, params={
            "action": "query", "titles": "|".join(file_titles),
            "prop": "imageinfo", "iiprop": "url", "format": "json",
        }, timeout=8, headers=_WIKI_HEADERS)
        pages = r3.json().get("query", {}).get("pages", {}).values()

        # Preserve the ranked order
        url_map = {}
        for page in pages:
            info = page.get("imageinfo", [])
            if info:
                # Wikipedia normalises spaces↔underscores; store with underscores so
                # our lookup keys (built with underscores) always match.
                title = page.get("title", "").replace(" ", "_")
                url_map[title] = info[0]["url"]

        for ft in file_titles:
            url = url_map.get(ft.replace(" ", "_"))
            if not url:
                continue
            content = _fetch_svg(url)
            if content:
                name = ft.replace("File:", "").rsplit(".", 1)[0].replace("_", " ")
                results.append({
                    "name": name,
                    "url": url,
                    "format": "svg",
                    "source": "Wikipedia",
                    "content": content,
                })
    except Exception:
        pass
    return results


# ── Source 4: Clearbit Logo API ───────────────────────────────────────────────

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

    return results


# ── Main entry point ──────────────────────────────────────────────────────────

_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$")

# Matches "NYSE: $SQ", "$AAPL", "NASDAQ:MSFT", etc.
_TICKER_RE = re.compile(r'^(?:[A-Za-z]{1,10}:\s*)?\$?([A-Za-z]{1,5})$')

def _looks_like_domain(s: str) -> bool:
    return bool(_DOMAIN_RE.match(s.strip())) and " " not in s.strip()

def _clean_ticker(query: str) -> str:
    """Strip exchange prefix and $ from ticker-format queries.
    'NYSE: $SQ' → 'SQ',  '$AAPL' → 'AAPL',  others unchanged.
    """
    q = query.strip()
    if '$' in q or ':' in q:
        m = _TICKER_RE.match(q)
        if m:
            return m.group(1)
    return q

def normalize_url(url: str) -> str:
    """Ensure a URL has a scheme; default to https://."""
    url = url.strip()
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def find_logos(query: str, website_url: Optional[str] = None) -> list[dict]:
    """Search all sources and return deduplicated logo list."""
    results: list[dict] = []

    query = _clean_ticker(query)

    # If the query looks like a domain, use it directly for domain-based sources
    # and derive a plain company name for name-based sources.
    domain: Optional[str] = None
    name_query = query
    if _looks_like_domain(query):
        domain = query.strip().lower()
        if domain.startswith("www."):
            domain = domain[4:]
        # e.g. "block.xyz" → "block"
        name_query = domain.rsplit(".", 1)[0]
        if not website_url:
            website_url = normalize_url(query)

    results.extend(search_simple_icons(name_query))
    results.extend(search_wikimedia(name_query))
    results.extend(search_worldvectorlogo(name_query))
    results.extend(search_clearbit(name_query, domain=domain))

    if website_url:
        website_url = normalize_url(website_url)
        results.extend(search_website(website_url, query=name_query))

    # Deduplicate by URL
    seen: set[str] = set()
    unique: list[dict] = []
    for logo in results:
        if logo["url"] not in seen:
            seen.add(logo["url"])
            unique.append(logo)

    return unique
