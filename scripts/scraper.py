"""
scraper.py — Website scraper for the Ad Asset Builder Agent.

Fetches the homepage and returns:
  - Raw page text (for Claude to understand the brand and products)
  - All internal links (for Claude to select category sitelinks)

All interpretation — which links are categories, what the brand sells,
what the selling points are — is done by Claude, not by this module.

Standalone usage:
    python scripts/scraper.py https://example.com
"""

import copy
import json
import logging
import re
import sys
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUEST_TIMEOUT = 10
MAX_NAV_PAGES = 12
HOMEPAGE_TEXT_LIMIT = 5000   # chars of homepage text sent to Claude
PAGE_TEXT_LIMIT = 2000        # chars per additional page

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; AssetBuilderBot/1.0; "
        "+https://github.com/omniac/asset-agent)"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Links that are never useful for sitelinks regardless of site type
_ALWAYS_SKIP = re.compile(
    r"cart|kosaric|panier|warenkorb|winkelwagen|"
    r"checkout|login|register|account|wishlist|"
    r"privacy|terms|cookie|sitemap|search|"
    r"wp-admin|wp-login|wp-json|feed|rss|xmlrpc",
    re.I,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ScraperError(Exception):
    pass


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def scrape_site(url: str) -> dict:
    """
    Fetch a website and return content for Claude to analyze.

    Returns:
        {
            "base_url":     str,
            "language":     str | None,
            "homepage":     {url, url_path, title, text},
            "all_links":    [{text, url}, ...],   # ALL internal links, Claude selects
            "nav_pages":    [{url, url_path, title, text}, ...],  # fetched pages
            "json_ld":      [dict, ...],
            "open_graph":   {str: str, ...},
            "scrape_errors": [str, ...],
        }
    """
    errors = []
    base_url = _normalize_url(url)

    session = requests.Session()
    session.headers.update(HEADERS)

    # --- Fetch homepage ---
    response = _fetch(base_url, session)
    if response is None:
        raise ScraperError(
            f"Could not reach homepage at {base_url}. "
            "Check the URL and your internet connection."
        )

    soup = BeautifulSoup(response.text, "lxml")
    json_ld = _extract_json_ld(soup)
    open_graph = _extract_open_graph(soup)
    language = _extract_language(soup)

    homepage = {
        "url": base_url,
        "url_path": "/",
        "title": _extract_title(soup),
        "text": _extract_page_text(soup, max_chars=HOMEPAGE_TEXT_LIMIT),
    }

    # --- Collect ALL internal links (Claude will decide which are categories) ---
    all_links = _extract_all_internal_links(soup, base_url)

    # --- Fetch the top linked pages to give Claude more product/category context ---
    nav_pages = _scrape_top_pages(all_links, session, max_pages=MAX_NAV_PAGES)

    return {
        "base_url": base_url,
        "language": language,
        "homepage": homepage,
        "all_links": all_links,
        "nav_pages": nav_pages,
        "json_ld": json_ld,
        "open_graph": open_graph,
        "scrape_errors": errors,
    }


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
    )
    return normalized.geturl().rstrip("/")


def _same_domain(url: str, base_url: str) -> bool:
    base_host = urlparse(base_url).netloc.lstrip("www.")
    url_host = urlparse(url).netloc.lstrip("www.")
    return url_host == base_host or url_host.endswith("." + base_host)


def _absolute_url(href: str, base_url: str) -> str | None:
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return None
    absolute = urljoin(base_url, href)
    parsed = urlparse(absolute)
    if parsed.scheme not in ("http", "https"):
        return None
    return absolute


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------

def _is_allowed_by_robots(base_url: str, target_url: str) -> bool:
    try:
        rp = RobotFileParser()
        rp.set_url(base_url.rstrip("/") + "/robots.txt")
        rp.read()
        return rp.can_fetch("AssetBuilderBot", target_url)
    except Exception:
        return True


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

def _fetch(url: str, session: requests.Session) -> requests.Response | None:
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        response.raise_for_status()
        return response
    except requests.exceptions.Timeout:
        logger.warning("Timeout fetching %s", url)
    except requests.exceptions.HTTPError as e:
        logger.warning("HTTP %s for %s", e.response.status_code, url)
    except requests.exceptions.RequestException as e:
        logger.warning("Request error for %s: %s", url, e)
    return None


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------

def _extract_title(soup: BeautifulSoup) -> str | None:
    h1 = soup.find("h1")
    if h1:
        text = h1.get_text(strip=True)
        if text:
            return text
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        return title_tag.string.strip()
    return None


def _extract_page_text(soup: BeautifulSoup, max_chars: int = PAGE_TEXT_LIMIT) -> str:
    """Clean body text with nav/footer/script removed, truncated to max_chars."""
    soup_copy = copy.copy(soup)
    for tag in soup_copy(["nav", "header", "footer", "script", "style",
                           "aside", "noscript", "svg", "iframe"]):
        tag.decompose()
    text = soup_copy.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _extract_language(soup: BeautifulSoup) -> str | None:
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang", "").strip():
        return html_tag["lang"].strip()
    meta_lang = soup.find("meta", attrs={"http-equiv": re.compile(r"content-language", re.I)})
    if meta_lang and meta_lang.get("content", "").strip():
        return meta_lang["content"].strip()
    return None


def _link_display_text(a_tag) -> str | None:
    """Visible text → img alt → last URL path segment."""
    text = a_tag.get_text(strip=True)
    if text:
        return text[:80]
    img = a_tag.find("img")
    if img and img.get("alt", "").strip():
        return img["alt"].strip()[:80]
    href = a_tag.get("href", "")
    segment = urlparse(href).path.rstrip("/").split("/")[-1]
    segment = segment.replace("-", " ").replace("_", " ").strip()
    return segment[:80] if segment else None


# ---------------------------------------------------------------------------
# JSON-LD and Open Graph
# ---------------------------------------------------------------------------

def _extract_json_ld(soup: BeautifulSoup) -> list[dict]:
    objects = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                objects.extend(data)
            elif isinstance(data, dict):
                objects.append(data)
        except (json.JSONDecodeError, TypeError):
            pass
    return objects


def _extract_open_graph(soup: BeautifulSoup) -> dict:
    og = {}
    for meta in soup.find_all("meta"):
        prop = meta.get("property", "") or meta.get("name", "")
        if prop.startswith("og:"):
            content = meta.get("content", "").strip()
            if content:
                og[prop[3:]] = content
    return og


# ---------------------------------------------------------------------------
# Link extraction — lightly filtered, Claude decides what's useful
# ---------------------------------------------------------------------------

def _extract_all_internal_links(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """
    Collect all unique internal links from the page.
    Only filters out obviously useless URLs (cart, login, wp-admin, etc.).
    Claude decides which links are product categories worth using as sitelinks.
    """
    seen: set[str] = set()
    links = []

    for a in soup.find_all("a", href=True):
        abs_url = _absolute_url(a["href"], base_url)
        if not abs_url or not _same_domain(abs_url, base_url):
            continue
        # Strip query strings and fragments for dedup
        clean = abs_url.split("?")[0].split("#")[0].rstrip("/")
        if not clean or clean == base_url.rstrip("/"):
            continue
        if clean in seen:
            continue
        if _ALWAYS_SKIP.search(clean):
            continue
        text = _link_display_text(a)
        if not text:
            continue
        seen.add(clean)
        links.append({"text": text, "url": abs_url.split("?")[0].split("#")[0]})

    return links


# ---------------------------------------------------------------------------
# Fetch top pages for additional context
# ---------------------------------------------------------------------------

def _scrape_top_pages(
    all_links: list[dict], session: requests.Session, max_pages: int = MAX_NAV_PAGES
) -> list[dict]:
    """
    Fetch the first max_pages unique internal links to give Claude page-level context.
    Skips individual product pages (very long URL slugs are a reliable signal).
    """
    pages = []
    for link in all_links:
        if len(pages) >= max_pages:
            break
        url = link["url"]
        # Skip single-product pages: path has 2+ segments and last segment is long
        path = urlparse(url).path.rstrip("/")
        segments = [s for s in path.split("/") if s]
        if len(segments) >= 2 and len(segments[-1]) > 40:
            continue
        resp = _fetch(url, session)
        if resp is None:
            continue
        soup = BeautifulSoup(resp.text, "lxml")
        pages.append({
            "url": url,
            "url_path": urlparse(url).path,
            "title": _extract_title(soup),
            "text": _extract_page_text(soup, max_chars=PAGE_TEXT_LIMIT),
        })
    return pages


# ---------------------------------------------------------------------------
# Standalone execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scraper.py <url>", file=sys.stderr)
        sys.exit(1)

    logging.basicConfig(level=logging.INFO)
    data = scrape_site(sys.argv[1])

    sys.stdout.buffer.write(f"Language: {data['language']}\n".encode("utf-8"))
    sys.stdout.buffer.write(f"Homepage: {data['homepage']['title']}\n".encode("utf-8"))
    sys.stdout.buffer.write(f"All links found: {len(data['all_links'])}\n".encode("utf-8"))
    sys.stdout.buffer.write(f"Pages fetched: {len(data['nav_pages'])}\n".encode("utf-8"))
    for lnk in data["all_links"]:
        sys.stdout.buffer.write(f"  {lnk['text'][:40]:<42} {lnk['url']}\n".encode("utf-8"))
