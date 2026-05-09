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
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from urllib.parse import urljoin, urlparse

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
TIMEOUT = 5

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


def _fetch_png(url: str) -> Optional[bytes]:
    """Fetch a PNG and return it only if it has a transparency (alpha) channel."""
    try:
        r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
        if r.status_code != 200 or len(r.content) < 300:
            return None
        ct = r.headers.get("content-type", "")
        if "png" not in ct and not url.lower().split("?")[0].endswith(".png"):
            return None
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(r.content))
        if img.mode in ("RGBA", "LA", "PA"):
            return r.content
    except Exception:
        pass
    return None


def _fetch_logo(url: str) -> tuple[Optional[bytes], str]:
    """Try SVG first, then transparent PNG. Returns (content, format)."""
    content = _fetch_svg(url)
    if content:
        return content, "svg"
    content = _fetch_png(url)
    if content:
        return content, "png"
    return None, ""


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
                    ranked.insert(0, (0, "exact", icon))
                # Substring match only when both sides are substantial (≥4 chars)
                # to avoid short titles like "C" or "R" matching inside longer queries
                elif len(t) >= 4 and len(q) >= 4 and (q in t or t in q):
                    ranked.append((1, "substring", icon))
            top = ranked[:5]
            def _fetch_icon(item):
                _, match_type, icon = item
                slug = icon.get("slug") or _simple_slug(icon["title"])
                url = _SIMPLE_ICONS_CDN.format(slug=slug)
                content = _fetch_svg(url)
                return (icon["title"], url, content, match_type) if content else None

            with ThreadPoolExecutor(max_workers=len(top)) as ex:
                for res in ex.map(_fetch_icon, top):
                    if res:
                        title, url, content, match_type = res
                        results.append({
                            "name": title,
                            "url": url,
                            "format": "svg",
                            "source": "Simple Icons",
                            "content": content,
                            "match_type": match_type,
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

    # For each base slug, try plain then numbered variants (-1 through -3)
    slugs_to_try = []
    for base in base_candidates:
        slugs_to_try.append(base)
        for n in range(1, 4):
            slugs_to_try.append(f"{base}-{n}")

    def _try_wvl(slug: str):
        url = _WVL_CDN.format(slug=slug)
        content = _fetch_svg(url)
        return {"name": query, "url": url, "format": "svg",
                "source": "World Vector Logo", "content": content} if content else None

    with ThreadPoolExecutor(max_workers=len(slugs_to_try)) as ex:
        hits = [r for r in ex.map(_try_wvl, slugs_to_try) if r]

    hits.reverse()  # higher-numbered (newer) variants first
    return hits


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

        # Keep SVGs and transparent PNGs that contain "logo" (skip Wiki system files)
        system = {"commons-logo", "wikinews-logo", "wikiquote-logo", "wikibooks-logo",
                  "wikiversity-logo", "wiktionary-logo", "wikivoyage-logo"}
        logo_files = [
            img for img in images
            if img.lower().endswith((".svg", ".png"))
            and "logo" in img.lower()
            and img.lower().replace("-", "").replace("_", "").replace(" ", "").split(".")[0] not in system
        ]

        if not logo_files:
            return results

        # SVGs first, then PNGs; within each group prefer recent years
        def _file_rank(name: str):
            ext_rank = 0 if name.lower().endswith(".svg") else 1
            n = name.lower()
            if "historical" in n or "wordmark" in n:
                return (ext_rank, 1, 0)
            years = re.findall(r"\b(19|20)\d{2}\b", name)
            return (ext_rank, 0, -int(years[-1])) if years else (ext_rank, 0, 1)

        logo_files.sort(key=_file_rank)

        file_titles = [f"File:{img}" for img in logo_files[:6]]
        r3 = requests.get(_WIKI_API, params={
            "action": "query", "titles": "|".join(file_titles),
            "prop": "imageinfo", "iiprop": "url", "format": "json",
        }, timeout=8, headers=_WIKI_HEADERS)
        pages = r3.json().get("query", {}).get("pages", {}).values()

        url_map = {}
        for page in pages:
            info = page.get("imageinfo", [])
            if info:
                title = page.get("title", "").replace(" ", "_")
                url_map[title] = info[0]["url"]

        for ft in file_titles:
            url = url_map.get(ft.replace(" ", "_"))
            if not url:
                continue
            if ft.lower().endswith(".svg"):
                content = _fetch_svg(url)
                fmt = "svg"
            else:
                content = _fetch_png(url)
                fmt = "png"
            if content:
                name = ft.replace("File:", "").rsplit(".", 1)[0].replace("_", " ")
                results.append({
                    "name": name,
                    "url": url,
                    "format": fmt,
                    "source": "Wikipedia",
                    "content": content,
                })
    except Exception:
        pass
    return results


# ── Source 3b: Wikimedia Commons direct search ───────────────────────────────

_COMMONS_LOGO_KEYWORDS = ("logo", "lockup", "wordmark", "brand", "icon")
_COMMONS_STALE_KEYWORDS = ("historical", "old", "vintage", "former", "previous")

def search_wikimedia_commons(query: str) -> list[dict]:
    results = []
    try:
        # Try both "logo SVG" and "lockup SVG" — companies often store lockup variants
        seen_titles: set[str] = set()
        hits = []
        for term in (f"{query} logo", f"{query} lockup", f"{query} lockup logo"):
            r = requests.get(_COMMONS_API, params={
                "action": "query", "list": "search",
                "srsearch": term,
                "srnamespace": 6, "format": "json", "srlimit": 5,
            }, timeout=8, headers=_WIKI_HEADERS)
            for h in r.json().get("query", {}).get("search", []):
                if h["title"] not in seen_titles:
                    seen_titles.add(h["title"])
                    hits.append(h)

        file_titles = []
        for hit in hits:
            t = hit["title"].lower()
            if t.endswith((".svg", ".png")) and \
               any(kw in t for kw in _COMMONS_LOGO_KEYWORDS) and \
               not any(kw in t for kw in _COMMONS_STALE_KEYWORDS):
                file_titles.append(hit["title"])

        if not file_titles:
            return results

        r2 = requests.get(_COMMONS_API, params={
            "action": "query", "titles": "|".join(file_titles[:10]),
            "prop": "imageinfo", "iiprop": "url", "format": "json",
        }, timeout=8, headers=_WIKI_HEADERS)
        pages = r2.json().get("query", {}).get("pages", {}).values()

        for page in pages:
            info = page.get("imageinfo", [])
            if not info:
                continue
            url = info[0]["url"].split("?")[0]  # strip UTM params
            content, fmt = _fetch_logo(url)
            if content:
                name = page.get("title", "").replace("File:", "").rsplit(".", 1)[0].replace("_", " ")
                results.append({
                    "name": name,
                    "url": url,
                    "format": fmt,
                    "source": "Wikimedia Commons",
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

# URL substrings that identify CMS/platform assets, not the company's own logo
_SCRAPE_BLOCKLIST = (
    "drupal", "wordpress", "wp-content", "wp-includes",
    "joomla", "magento", "shopify", "squarespace", "webflow",
    "/sites/default/files/",   # Drupal upload path
    "cookiebot", "onetrust", "cookiepro",
    "google-analytics", "googletagmanager",
)


def _same_base_domain(url_a: str, url_b: str) -> bool:
    """True when both URLs share the same registrable domain (ignoring subdomains)."""
    def base(u: str) -> str:
        host = urlparse(u).netloc.lower().removeprefix("www.")
        parts = host.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else host
    return base(url_a) == base(url_b)


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

            # Skip images hosted on a different domain (e.g. Drupal CDN, CMS assets)
            if not _same_base_domain(full_url, website_url):
                continue
            # Skip known CMS / platform logo paths
            if any(p in full_url.lower() for p in _SCRAPE_BLOCKLIST):
                continue

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
                        "source": "SVG Favicon",
                        "content": content,
                    })

    except Exception:
        pass

    return results


# ── Logo scoring ─────────────────────────────────────────────────────────────

_SOURCE_SCORES = {
    "Simple Icons": 90,
    "Wikimedia Commons": 88,
    "Clearbit": 85,
    "Company Website": 80,
    "World Vector Logo": 60,
    "Wikipedia": 50,
    "SVG Favicon": 30,
}

_STALE_KEYWORDS = ("historical", "vintage", "classic", "retro", "antique")


def _score_logo(logo: dict) -> int:
    score = _SOURCE_SCORES.get(logo["source"], 50)
    name = logo["name"].lower()

    if any(kw in name for kw in _STALE_KEYWORDS):
        score -= 40
    if re.search(r'\bold\b', name):
        score -= 20

    for yr_str in re.findall(r'\b((?:19|20)\d{2})\b', name):
        if int(yr_str) < 2010:
            score -= 30

    if logo["source"] == "World Vector Logo":
        m = re.search(r'-(\d+)\.svg$', logo["url"])
        if m:
            score -= int(m.group(1)) * 8

    # Penalize Simple Icons results that matched only as a substring (e.g. "AdBlock"
    # surfacing when query is "block") — keep them below more authoritative source hits.
    if logo["source"] == "Simple Icons" and logo.get("match_type") == "substring":
        score -= 35

    return score


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
    """Search all sources in parallel and return a deduplicated, scored logo list."""
    query = _clean_ticker(query)

    domain: Optional[str] = None
    name_query = query
    if _looks_like_domain(query):
        domain = query.strip().lower().removeprefix("www.")
        name_query = domain.rsplit(".", 1)[0]
        if not website_url:
            website_url = normalize_url(query)

    tasks: list = [
        lambda: search_simple_icons(name_query),
        lambda: search_wikimedia(name_query),
        lambda: search_wikimedia_commons(name_query),
        lambda: search_worldvectorlogo(name_query),
        lambda nq=name_query, d=domain: search_clearbit(nq, domain=d),
    ]
    if website_url:
        url = normalize_url(website_url)
        tasks.append(lambda u=url, nq=name_query: search_website(u, query=nq))

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        for fut in as_completed(ex.submit(t) for t in tasks):
            try:
                results.extend(fut.result())
            except Exception:
                pass

    seen: set[str] = set()
    unique: list[dict] = []
    for logo in results:
        if logo["url"] not in seen:
            seen.add(logo["url"])
            logo["score"] = _score_logo(logo)
            unique.append(logo)

    unique.sort(key=lambda x: x["score"], reverse=True)
    return unique
