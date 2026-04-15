"""
scraper.py — Website scraper for the Ad Asset Builder Agent.

Layer 1 of the two-layer approach: code extraction only.
Layer 2 (AI interpretation) happens in google_ads_assets.py via Claude.

Standalone usage:
    python scripts/scraper.py https://example.com
"""

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

CURRENCY_SYMBOLS = {"£": "GBP", "€": "EUR", "$": "USD", "¥": "JPY", "₹": "INR", "kr": "SEK"}

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
    """Scrape a website and return a structured data dict for Claude analysis."""
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
    homepage_data = _parse_homepage(soup, base_url)
    json_ld = _extract_json_ld(soup)
    open_graph = _extract_open_graph(soup)

    nav_links = homepage_data.pop("nav_links")

    # --- Scrape nav pages (up to MAX_NAV_PAGES) ---
    nav_pages = _scrape_nav_pages(nav_links, session)

    # --- Find and scrape secondary pages ---
    # Look in both nav links and footer links
    footer_links = _extract_footer_links(soup, base_url)
    all_links = nav_links + footer_links
    secondary_map = _find_secondary_pages(all_links, base_url)
    secondary_pages = _scrape_secondary_pages(secondary_map, session)

    return {
        "base_url": base_url,
        "brand_name": homepage_data.get("brand_name"),
        "language": homepage_data.get("language"),
        "currency": homepage_data.get("currency"),
        "tagline": homepage_data.get("tagline"),
        "trust_signals": homepage_data.get("trust_signals", []),
        "nav_links": nav_links,
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
    # Lowercase scheme and host, preserve path case
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
# Homepage parsing
# ---------------------------------------------------------------------------

def _parse_homepage(soup: BeautifulSoup, base_url: str) -> dict:
    """
    Extract structured data from the homepage HTML.
    Returns a dict with: brand_name, language, currency, tagline,
                         trust_signals, nav_links.
    """
    json_ld_objects = _extract_json_ld(soup)

    return {
        "brand_name": _extract_brand_name(soup, json_ld_objects),
        "language": _extract_language(soup),
        "currency": _extract_currency(soup, json_ld_objects),
        "tagline": _extract_tagline(soup),
        "trust_signals": _extract_trust_signals(soup, json_ld_objects),
        "nav_links": _extract_nav_links(soup, base_url),
    }


def _extract_brand_name(soup: BeautifulSoup, json_ld: list[dict]) -> str | None:
    """
    Try multiple sources in priority order:
    1. og:site_name meta tag
    2. schema.org Organization/LocalBusiness name in JSON-LD
    3. <title> tag (stripped of common suffixes)
    4. Logo <img> alt text
    5. Footer text (first meaningful short string)
    """
    # 1. og:site_name
    og_site = soup.find("meta", property="og:site_name")
    if og_site and og_site.get("content", "").strip():
        return og_site["content"].strip()

    # 2. JSON-LD Organization/LocalBusiness
    for obj in json_ld:
        graph = obj.get("@graph", [obj])
        for item in graph:
            if item.get("@type") in ("Organization", "LocalBusiness", "Store", "WebSite"):
                name = item.get("name", "").strip()
                if name:
                    return name

    # 3. <title> stripped of common noise
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        title = title_tag.string.strip()
        for sep in [" | ", " – ", " - ", " :: ", " · "]:
            if sep in title:
                title = title.split(sep)[0].strip()
                break
        if title:
            return title

    # 4. Logo alt text
    logo = soup.find("img", class_=re.compile(r"logo", re.I))
    if not logo:
        logo = soup.find("img", alt=re.compile(r"logo", re.I))
    if logo and logo.get("alt", "").strip():
        alt = logo["alt"].strip()
        if alt.lower() not in ("logo", "site logo", "brand logo"):
            return alt

    # 5. Footer brand text — look for short text in footer
    footer = soup.find("footer")
    if footer:
        for elem in footer.find_all(["span", "p", "div"], recursive=False):
            text = elem.get_text(strip=True)
            if 2 < len(text) < 40 and not text.startswith("©"):
                return text

    return None


def _extract_language(soup: BeautifulSoup) -> str | None:
    """Extract BCP-47 language code from <html lang="">."""
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang", "").strip():
        return html_tag["lang"].strip()
    # Fallback: content-language meta
    meta_lang = soup.find("meta", attrs={"http-equiv": re.compile(r"content-language", re.I)})
    if meta_lang and meta_lang.get("content", "").strip():
        return meta_lang["content"].strip()
    return None


def _extract_currency(soup: BeautifulSoup, json_ld: list[dict]) -> str | None:
    """Detect currency from meta tags, JSON-LD, or visible price strings."""
    # og:price:currency
    og_currency = soup.find("meta", property="og:price:currency")
    if og_currency and og_currency.get("content", "").strip():
        return og_currency["content"].strip()

    # product:price:currency
    product_currency = soup.find("meta", property="product:price:currency")
    if product_currency and product_currency.get("content", "").strip():
        return product_currency["content"].strip()

    # JSON-LD offers
    for obj in json_ld:
        graph = obj.get("@graph", [obj])
        for item in graph:
            offers = item.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            currency = offers.get("priceCurrency", "").strip()
            if currency:
                return currency

    # Scan visible text for currency symbols
    text = soup.get_text()
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in text:
            return code

    return None


def _extract_tagline(soup: BeautifulSoup) -> str | None:
    """Extract the hero/main tagline — typically the first prominent <h1>."""
    h1 = soup.find("h1")
    if h1:
        text = h1.get_text(strip=True)
        if text and len(text) < 200:
            return text

    # Fallback: og:description
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content", "").strip():
        return og_desc["content"].strip()

    # Fallback: meta description
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content", "").strip():
        return meta_desc["content"].strip()

    return None


def _extract_trust_signals(soup: BeautifulSoup, json_ld: list[dict]) -> list[str]:
    """
    Find trust signals: phone, email, address, certifications, review count,
    free shipping/returns mentions, awards.
    """
    signals = []
    text = soup.get_text(" ", strip=True)

    # Phone numbers
    phones = re.findall(r'\+?[\d\s\-\(\)]{8,}', text)
    for phone in phones[:2]:
        cleaned = phone.strip()
        if len(re.sub(r'\D', '', cleaned)) >= 7:
            signals.append(f"Phone: {cleaned}")

    # Email addresses
    emails = re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', text)
    for email in emails[:2]:
        if not email.endswith(('.png', '.jpg', '.svg')):
            signals.append(f"Email: {email}")

    # Free shipping / returns mentions
    for pattern, label in [
        (r'free\s+shipping', "Free Shipping"),
        (r'free\s+(delivery|returns|return)', "Free Returns/Delivery"),
        (r'money.back\s+guarantee', "Money-Back Guarantee"),
        (r'(\d+).day\s+(return|refund)', "Day Return Policy"),
        (r'(\d[\d,]+)\+?\s+(customer|review|order)', "Customer/Review Count"),
        (r'since\s+(\d{4})', "Years in Business"),
        (r'(\d[\d.]+)/5\s+(star|rating)', "Star Rating"),
        (r'(\d[\d,]+)\s+(reviews|ratings)', "Review Count"),
    ]:
        match = re.search(pattern, text, re.I)
        if match:
            signals.append(f"{label}: {match.group(0).strip()}")

    # Address from JSON-LD
    for obj in json_ld:
        graph = obj.get("@graph", [obj])
        for item in graph:
            address = item.get("address", {})
            if isinstance(address, dict):
                parts = [
                    address.get("streetAddress", ""),
                    address.get("addressLocality", ""),
                    address.get("addressCountry", ""),
                ]
                addr_str = ", ".join(p for p in parts if p)
                if addr_str:
                    signals.append(f"Address: {addr_str}")
                    break

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for s in signals:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            unique.append(s)

    return unique


def _extract_nav_links(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """
    Extract main navigation links. Returns list of {"text": str, "url": str}.
    Only same-domain links, deduped by URL.
    """
    links = []
    seen_urls = set()

    # Primary: look for <nav> elements
    nav_elements = soup.find_all("nav")
    if not nav_elements:
        # Fallback: header links
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
                continue  # skip homepage link
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
            key = prop[3:]  # strip "og:" prefix
            content = meta.get("content", "").strip()
            if content:
                og[key] = content
    return og


# ---------------------------------------------------------------------------
# Individual page scraping
# ---------------------------------------------------------------------------

def _scrape_page(url: str, session: requests.Session) -> dict | None:
    """
    Fetch and extract data from a single page.
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

    # Title: prefer <h1>, fall back to <title>
    title = None
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            title = title_tag.string.strip()

    # Meta description
    meta_desc = soup.find("meta", attrs={"name": "description"})
    meta_description = None
    if meta_desc and meta_desc.get("content", "").strip():
        meta_description = meta_desc["content"].strip()

    # Body excerpt: first 2-3 meaningful sentences
    body_excerpt = _extract_body_excerpt(soup)

    return {
        "url": url,
        "url_path": parsed.path,
        "title": title,
        "meta_description": meta_description,
        "body_excerpt": body_excerpt,
    }


def _extract_body_excerpt(soup: BeautifulSoup) -> str | None:
    """
    Extract the first 2-3 content sentences from the page body.
    Skips navigation, header, footer, and short boilerplate paragraphs.
    """
    # Remove nav, header, footer, script, style from a copy
    for tag in soup(["nav", "header", "footer", "script", "style", "aside"]):
        tag.decompose()

    sentences = []
    for p in soup.find_all("p"):
        text = p.get_text(strip=True)
        if len(text) > 20:  # skip short boilerplate
            sentences.append(text)
        if len(sentences) >= 3:
            break

    if sentences:
        return " ".join(sentences[:3])
    return None


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
    # Fill None for slugs that weren't found at all
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
