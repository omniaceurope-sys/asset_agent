"""
scraper.py — Website scraper for the Ad Asset Builder Agent.

Fetches pages and returns raw text content for Claude to analyze.
URL discovery and HTTP fetching are handled here; all interpretation
(brand, selling points, products, trust signals) is done by Claude.

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
MAX_NAV_PAGES = 15
HOMEPAGE_TEXT_LIMIT = 4000   # chars of homepage text to send Claude
PAGE_TEXT_LIMIT = 2000        # chars per nav/secondary page

SECONDARY_PAGE_SLUGS = [
    "about", "contact", "shipping", "delivery",
    "returns", "refund", "faq", "reviews",
    "testimonials", "blog", "sale", "offers", "deals",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; AssetBuilderBot/1.0; "
        "+https://github.com/omniac/asset-agent)"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

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
    Fetch a website and return raw page content for Claude to analyze.

    Returns:
        {
            "base_url":        str,
            "language":        str | None,   # from <html lang="">
            "homepage":        {url, url_path, title, text},
            "nav_pages":       [{url, url_path, title, text}, ...],
            "secondary_pages": {slug: {url, url_path, title, text} | None, ...},
            "json_ld":         [dict, ...],
            "open_graph":      {str: str, ...},
            "scrape_errors":   [str, ...],
        }
    """
    errors = []
    base_url = _normalize_url(url)

    session = requests.Session()
    session.headers.update(HEADERS)

    # --- Fetch and parse homepage ---
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
    nav_links = _extract_nav_links(soup, base_url)

    homepage = {
        "url": base_url,
        "url_path": "/",
        "title": _extract_title(soup),
        "text": _extract_page_text(soup, max_chars=HOMEPAGE_TEXT_LIMIT),
    }

    # --- Scrape nav pages (up to MAX_NAV_PAGES) ---
    nav_pages = _scrape_nav_pages(nav_links, session)

    # --- Find and scrape secondary pages ---
    footer_links = _extract_footer_links(soup, base_url)
    all_links = nav_links + footer_links
    secondary_map = _find_secondary_pages(all_links, base_url)
    secondary_pages = _scrape_secondary_pages(secondary_map, session)

    return {
        "base_url": base_url,
        "language": language,
        "homepage": homepage,
        "nav_pages": nav_pages,
        "secondary_pages": secondary_pages,
        "json_ld": json_ld,
        "open_graph": open_graph,
        "scrape_errors": errors,
    }


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def _normalize_url(url: str) -> str:
    """Ensure url has a scheme and strip trailing slash."""
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
    )
    result = normalized.geturl().rstrip("/")
    return result


def _same_domain(url: str, base_url: str) -> bool:
    """Return True if url belongs to the same domain as base_url."""
    base_host = urlparse(base_url).netloc.lstrip("www.")
    url_host = urlparse(url).netloc.lstrip("www.")
    return url_host == base_host or url_host.endswith("." + base_host)


def _absolute_url(href: str, base_url: str) -> str | None:
    """Convert a potentially relative href to an absolute URL, or None if invalid."""
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
    """
    Check robots.txt for the given URL. Fail-open: if robots.txt can't be
    fetched, we assume scraping is allowed.
    """
    try:
        rp = RobotFileParser()
        robots_url = base_url.rstrip("/") + "/robots.txt"
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch("AssetBuilderBot", target_url)
    except Exception:
        return True  # fail-open


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

def _fetch(url: str, session: requests.Session) -> requests.Response | None:
    """
    Fetch a URL. Returns the Response or None on any error.
    Logs a warning on failure (not an exception — non-fatal for individual pages).
    """
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
# Page content extraction
# ---------------------------------------------------------------------------

def _extract_title(soup: BeautifulSoup) -> str | None:
    """Extract page title: prefer <h1>, fall back to <title> tag."""
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
    """
    Extract clean readable text from a page.
    Removes nav, header, footer, script, style, and other non-content elements.
    Collapses whitespace and truncates to max_chars.
    """
    soup_copy = copy.copy(soup)
    for tag in soup_copy(["nav", "header", "footer", "script", "style",
                           "aside", "noscript", "svg", "iframe"]):
        tag.decompose()
    text = soup_copy.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _extract_language(soup: BeautifulSoup) -> str | None:
    """Extract BCP-47 language code from <html lang="">."""
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang", "").strip():
        return html_tag["lang"].strip()
    meta_lang = soup.find("meta", attrs={"http-equiv": re.compile(r"content-language", re.I)})
    if meta_lang and meta_lang.get("content", "").strip():
        return meta_lang["content"].strip()
    return None


# ---------------------------------------------------------------------------
# JSON-LD and Open Graph
# ---------------------------------------------------------------------------

def _extract_json_ld(soup: BeautifulSoup) -> list[dict]:
    """Parse all JSON-LD script tags. Skips malformed blocks silently."""
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
    """Return a flat dict of og:* meta tag values."""
    og = {}
    for meta in soup.find_all("meta"):
        prop = meta.get("property", "") or meta.get("name", "")
        if prop.startswith("og:"):
            key = prop[3:]
            content = meta.get("content", "").strip()
            if content:
                og[key] = content
    return og


# ---------------------------------------------------------------------------
# Navigation and footer link extraction
# ---------------------------------------------------------------------------

def _extract_nav_links(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """
    Extract main navigation links. Returns list of {"text": str, "url": str}.
    Only same-domain links, deduped by URL.
    """
    links = []
    seen_urls = set()

    nav_elements = soup.find_all("nav")
    if not nav_elements:
        nav_elements = soup.find_all("header")

    for nav in nav_elements:
        for a in nav.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if not text or len(text) > 60:
                continue
            abs_url = _absolute_url(href, base_url)
            if not abs_url or not _same_domain(abs_url, base_url):
                continue
            if abs_url == base_url or abs_url == base_url + "/":
                continue
            if abs_url not in seen_urls:
                seen_urls.add(abs_url)
                links.append({"text": text, "url": abs_url})

    return links


def _extract_footer_links(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Extract links from the footer for secondary page discovery."""
    links = []
    seen_urls = set()
    footer = soup.find("footer")
    if not footer:
        return links
    for a in footer.find_all("a", href=True):
        text = a.get_text(strip=True)
        abs_url = _absolute_url(a["href"], base_url)
        if not abs_url or not _same_domain(abs_url, base_url):
            continue
        if abs_url not in seen_urls:
            seen_urls.add(abs_url)
            links.append({"text": text, "url": abs_url})
    return links


# ---------------------------------------------------------------------------
# Secondary page discovery
# ---------------------------------------------------------------------------

def _find_secondary_pages(links: list[dict], base_url: str) -> dict[str, str]:
    """
    Match link URLs against SECONDARY_PAGE_SLUGS.
    Returns {slug_category: url}. First match per category wins.
    """
    found = {}
    for link in links:
        url = link.get("url", "")
        path = urlparse(url).path.lower()
        text = link.get("text", "").lower()
        for slug in SECONDARY_PAGE_SLUGS:
            if slug in found:
                continue
            if slug in path or slug in text:
                found[slug] = url
    return found


# ---------------------------------------------------------------------------
# Individual page scraping
# ---------------------------------------------------------------------------

def _scrape_page(url: str, session: requests.Session) -> dict | None:
    """
    Fetch and extract raw text from a single page.
    Returns None if fetch fails or robots.txt disallows.
    """
    base_url = url.rsplit("/", 1)[0] if "/" in urlparse(url).path else url
    if not _is_allowed_by_robots(base_url, url):
        logger.warning("robots.txt disallows: %s", url)
        return None

    response = _fetch(url, session)
    if response is None:
        return None

    soup = BeautifulSoup(response.text, "lxml")
    parsed = urlparse(url)

    return {
        "url": url,
        "url_path": parsed.path,
        "title": _extract_title(soup),
        "text": _extract_page_text(soup, max_chars=PAGE_TEXT_LIMIT),
    }


# ---------------------------------------------------------------------------
# Batch scraping
# ---------------------------------------------------------------------------

def _scrape_nav_pages(nav_links: list[dict], session: requests.Session) -> list[dict]:
    """Scrape up to MAX_NAV_PAGES navigation links."""
    pages = []
    for link in nav_links[:MAX_NAV_PAGES]:
        page = _scrape_page(link["url"], session)
        if page is not None:
            pages.append(page)
    return pages


def _scrape_secondary_pages(
    secondary_map: dict[str, str],
    session: requests.Session,
) -> dict[str, dict | None]:
    """
    Scrape each secondary page URL.
    Returns {slug_category: page_dict | None}.
    """
    result = {}
    for slug, url in secondary_map.items():
        result[slug] = _scrape_page(url, session)
    for slug in SECONDARY_PAGE_SLUGS:
        result.setdefault(slug, None)
    return result


# ---------------------------------------------------------------------------
# Standalone execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scraper.py <url>", file=sys.stderr)
        sys.exit(1)

    logging.basicConfig(level=logging.INFO)
    data = scrape_site(sys.argv[1])
    print(json.dumps(data, indent=2, ensure_ascii=False))
