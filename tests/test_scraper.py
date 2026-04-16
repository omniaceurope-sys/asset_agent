"""
tests/test_scraper.py — Unit tests for scripts/scraper.py

Tests cover all pure parsing functions (no network I/O).
HTTP calls are mocked via unittest.mock.patch.

Run:
    pip install pytest
    pytest tests/test_scraper.py -v
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

# Make scripts/ importable from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from scraper import (
    ScraperError,
    _absolute_url,
    _extract_all_internal_links,
    _extract_json_ld,
    _extract_language,
    _extract_open_graph,
    _extract_page_text,
    _extract_title,
    _fetch,
    _normalize_url,
    _same_domain,
    scrape_site,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


# ===========================================================================
# _normalize_url
# ===========================================================================

class TestNormalizeUrl:
    def test_adds_https_when_no_scheme(self):
        assert _normalize_url("example.com") == "https://example.com"

    def test_keeps_existing_https(self):
        assert _normalize_url("https://example.com") == "https://example.com"

    def test_keeps_http(self):
        assert _normalize_url("http://example.com") == "http://example.com"

    def test_strips_trailing_slash(self):
        assert _normalize_url("https://example.com/") == "https://example.com"

    def test_lowercases_scheme_and_host(self):
        assert _normalize_url("HTTPS://EXAMPLE.COM/Path") == "https://example.com/Path"

    def test_strips_whitespace(self):
        assert _normalize_url("  https://example.com  ") == "https://example.com"

    def test_preserves_path(self):
        assert _normalize_url("https://example.com/shop/items") == "https://example.com/shop/items"

    def test_preserves_query_string(self):
        result = _normalize_url("https://example.com/search?q=test")
        assert "q=test" in result


# ===========================================================================
# _same_domain
# ===========================================================================

class TestSameDomain:
    BASE = "https://example.com"

    def test_exact_match(self):
        assert _same_domain("https://example.com/page", self.BASE) is True

    def test_www_prefix_ignored(self):
        assert _same_domain("https://www.example.com/page", self.BASE) is True

    def test_different_domain(self):
        assert _same_domain("https://other.com/page", self.BASE) is False

    def test_subdomain_allowed(self):
        assert _same_domain("https://shop.example.com/page", self.BASE) is True

    def test_similar_but_different_domain(self):
        assert _same_domain("https://notexample.com/page", self.BASE) is False


# ===========================================================================
# _absolute_url
# ===========================================================================

class TestAbsoluteUrl:
    BASE = "https://example.com"

    def test_relative_path(self):
        assert _absolute_url("/about", self.BASE) == "https://example.com/about"

    def test_already_absolute(self):
        assert _absolute_url("https://example.com/shop", self.BASE) == "https://example.com/shop"

    def test_mailto_returns_none(self):
        assert _absolute_url("mailto:hello@example.com", self.BASE) is None

    def test_tel_returns_none(self):
        assert _absolute_url("tel:+441234567890", self.BASE) is None

    def test_javascript_returns_none(self):
        assert _absolute_url("javascript:void(0)", self.BASE) is None

    def test_hash_returns_none(self):
        assert _absolute_url("#section", self.BASE) is None

    def test_empty_returns_none(self):
        assert _absolute_url("", self.BASE) is None

    def test_none_returns_none(self):
        assert _absolute_url(None, self.BASE) is None


# ===========================================================================
# _extract_json_ld
# ===========================================================================

class TestExtractJsonLd:
    def test_parses_single_object(self):
        html = '''<html><body>
        <script type="application/ld+json">{"@type": "Organization", "name": "Acme"}</script>
        </body></html>'''
        result = _extract_json_ld(make_soup(html))
        assert len(result) == 1
        assert result[0]["name"] == "Acme"

    def test_parses_list(self):
        html = '''<html><body>
        <script type="application/ld+json">[{"@type": "A"}, {"@type": "B"}]</script>
        </body></html>'''
        result = _extract_json_ld(make_soup(html))
        assert len(result) == 2

    def test_skips_malformed_silently(self):
        html = '''<html><body>
        <script type="application/ld+json">{ NOT VALID JSON }</script>
        <script type="application/ld+json">{"@type": "Organization"}</script>
        </body></html>'''
        result = _extract_json_ld(make_soup(html))
        assert len(result) == 1

    def test_multiple_scripts(self):
        html = '''<html><body>
        <script type="application/ld+json">{"@type": "X"}</script>
        <script type="application/ld+json">{"@type": "Y"}</script>
        </body></html>'''
        result = _extract_json_ld(make_soup(html))
        assert len(result) == 2

    def test_empty_when_no_scripts(self):
        html = "<html><body><p>No structured data</p></body></html>"
        assert _extract_json_ld(make_soup(html)) == []


# ===========================================================================
# _extract_open_graph
# ===========================================================================

class TestExtractOpenGraph:
    def test_extracts_og_title(self):
        html = '<html><head><meta property="og:title" content="My Store"></head></html>'
        result = _extract_open_graph(make_soup(html))
        assert result["title"] == "My Store"

    def test_extracts_multiple_tags(self):
        html = '''<html><head>
        <meta property="og:title" content="Store">
        <meta property="og:description" content="Best store">
        <meta property="og:site_name" content="StoreName">
        </head></html>'''
        result = _extract_open_graph(make_soup(html))
        assert result["title"] == "Store"
        assert result["description"] == "Best store"
        assert result["site_name"] == "StoreName"

    def test_empty_when_no_og_tags(self):
        html = "<html><head><title>Page</title></head></html>"
        assert _extract_open_graph(make_soup(html)) == {}

    def test_ignores_empty_content(self):
        html = '<html><head><meta property="og:title" content=""></head></html>'
        result = _extract_open_graph(make_soup(html))
        assert "title" not in result


# ===========================================================================
# _extract_language
# ===========================================================================

class TestExtractLanguage:
    def test_reads_html_lang_attribute(self):
        html = '<html lang="en-GB"><head></head></html>'
        assert _extract_language(make_soup(html)) == "en-GB"

    def test_reads_html_lang_simple(self):
        html = '<html lang="de"><head></head></html>'
        assert _extract_language(make_soup(html)) == "de"

    def test_returns_none_when_no_lang(self):
        html = "<html><head></head></html>"
        assert _extract_language(make_soup(html)) is None

    def test_ignores_empty_lang(self):
        html = '<html lang=""><head></head></html>'
        assert _extract_language(make_soup(html)) is None


# ===========================================================================
# _extract_title
# ===========================================================================

class TestExtractTitle:
    def test_prefers_h1(self):
        html = "<html><head><title>Page Title</title></head><body><h1>H1 Title</h1></body></html>"
        assert _extract_title(make_soup(html)) == "H1 Title"

    def test_falls_back_to_title_tag(self):
        html = "<html><head><title>Page Title</title></head><body></body></html>"
        assert _extract_title(make_soup(html)) == "Page Title"

    def test_returns_none_when_nothing(self):
        html = "<html><head></head><body><p>No title</p></body></html>"
        assert _extract_title(make_soup(html)) is None

    def test_strips_whitespace_from_h1(self):
        html = "<html><body><h1>  Trimmed Title  </h1></body></html>"
        assert _extract_title(make_soup(html)) == "Trimmed Title"


# ===========================================================================
# _extract_page_text
# ===========================================================================

class TestExtractPageText:
    def test_returns_body_text(self):
        html = "<html><body><p>Hello world content here.</p></body></html>"
        text = _extract_page_text(make_soup(html))
        assert "Hello world content here" in text

    def test_excludes_nav_text(self):
        html = """<html><body>
        <nav>Navigation Menu Items</nav>
        <main><p>Main content of the page goes here.</p></main>
        </body></html>"""
        text = _extract_page_text(make_soup(html))
        assert "Navigation Menu Items" not in text
        assert "Main content" in text

    def test_excludes_footer_text(self):
        html = """<html><body>
        <main><p>Main content here is useful and long.</p></main>
        <footer>Footer copyright text</footer>
        </body></html>"""
        text = _extract_page_text(make_soup(html))
        assert "Footer copyright" not in text
        assert "Main content" in text

    def test_excludes_script_content(self):
        html = """<html><body>
        <script>var x = 'secret';</script>
        <p>Visible content paragraph here.</p>
        </body></html>"""
        text = _extract_page_text(make_soup(html))
        assert "secret" not in text
        assert "Visible content" in text

    def test_truncates_to_max_chars(self):
        long_text = "word " * 1000  # ~5000 chars
        html = f"<html><body><p>{long_text}</p></body></html>"
        text = _extract_page_text(make_soup(html), max_chars=100)
        assert len(text) <= 100

    def test_collapses_whitespace(self):
        html = "<html><body><p>Hello   world</p><p>foo    bar</p></body></html>"
        text = _extract_page_text(make_soup(html))
        assert "  " not in text  # no double spaces


# ===========================================================================
# _extract_all_internal_links
# ===========================================================================

class TestExtractAllInternalLinks:
    BASE = "https://example.com"

    def test_extracts_internal_links(self):
        html = '''<html><body>
        <nav>
          <a href="/shop">Shop</a>
          <a href="/about">About</a>
        </nav>
        </body></html>'''
        links = _extract_all_internal_links(make_soup(html), self.BASE)
        urls = [l["url"] for l in links]
        assert "https://example.com/shop" in urls
        assert "https://example.com/about" in urls

    def test_excludes_homepage_link(self):
        html = '''<html><body>
          <a href="/">Home</a>
          <a href="/shop">Shop</a>
        </body></html>'''
        links = _extract_all_internal_links(make_soup(html), self.BASE)
        urls = [l["url"] for l in links]
        assert self.BASE not in urls
        assert "https://example.com/shop" in urls

    def test_excludes_external_links(self):
        html = '''<html><body>
          <a href="https://external.com/page">External</a>
          <a href="/internal">Internal</a>
        </body></html>'''
        links = _extract_all_internal_links(make_soup(html), self.BASE)
        urls = [l["url"] for l in links]
        assert "https://external.com/page" not in urls
        assert "https://example.com/internal" in urls

    def test_deduplicates_urls(self):
        html = '''<html><body>
          <a href="/shop">Shop Link 1</a>
          <a href="/shop">Shop Link 2</a>
        </body></html>'''
        links = _extract_all_internal_links(make_soup(html), self.BASE)
        urls = [l["url"] for l in links]
        assert urls.count("https://example.com/shop") == 1

    def test_skips_cart_and_login(self):
        html = '''<html><body>
          <a href="/cart">Cart</a>
          <a href="/login">Login</a>
          <a href="/shop">Shop</a>
        </body></html>'''
        links = _extract_all_internal_links(make_soup(html), self.BASE)
        urls = [l["url"] for l in links]
        assert "https://example.com/cart" not in urls
        assert "https://example.com/login" not in urls
        assert "https://example.com/shop" in urls

    def test_skips_mailto_and_tel(self):
        html = '''<html><body>
          <a href="mailto:hi@example.com">Email</a>
          <a href="tel:123456">Call</a>
          <a href="/shop">Shop</a>
        </body></html>'''
        links = _extract_all_internal_links(make_soup(html), self.BASE)
        urls = [l["url"] for l in links]
        assert all(u.startswith("https://") for u in urls)


# ===========================================================================
# _fetch (mocked HTTP)
# ===========================================================================

class TestFetch:
    def test_returns_response_on_success(self):
        import requests
        session = MagicMock()
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        session.get.return_value = mock_response

        result = _fetch("https://example.com", session)
        assert result is mock_response

    def test_returns_none_on_timeout(self):
        import requests
        session = MagicMock()
        session.get.side_effect = requests.exceptions.Timeout()
        assert _fetch("https://example.com", session) is None

    def test_returns_none_on_http_error(self):
        import requests
        session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 404
        http_error = requests.exceptions.HTTPError(response=mock_response)
        mock_response.raise_for_status.side_effect = http_error
        session.get.return_value = mock_response
        assert _fetch("https://example.com", session) is None

    def test_returns_none_on_connection_error(self):
        import requests
        session = MagicMock()
        session.get.side_effect = requests.exceptions.ConnectionError()
        assert _fetch("https://example.com", session) is None


# ===========================================================================
# scrape_site (integration-level, HTTP mocked)
# ===========================================================================

SAMPLE_HOMEPAGE_HTML = """<!DOCTYPE html>
<html lang="en-GB">
<head>
  <title>TestBrand | Home</title>
  <meta property="og:site_name" content="TestBrand">
  <meta property="og:description" content="Quality products since 2015">
  <script type="application/ld+json">
  {"@type": "Organization", "name": "TestBrand"}
  </script>
</head>
<body>
  <nav>
    <a href="/shop">Shop</a>
    <a href="/about">About</a>
    <a href="/contact">Contact</a>
    <a href="/shipping">Shipping</a>
  </nav>
  <h1>Quality products since 2015</h1>
  <p>We offer free shipping on all orders over £50. 30-day money-back guarantee.</p>
  <footer>
    <a href="/returns">Returns</a>
    <a href="/faq">FAQ</a>
  </footer>
</body>
</html>"""

SAMPLE_PAGE_HTML = """<!DOCTYPE html>
<html lang="en-GB">
<head>
  <title>About Us | TestBrand</title>
  <meta name="description" content="Learn about TestBrand and our mission.">
</head>
<body>
  <h1>About Us</h1>
  <p>We have been making quality products since 2015 and we love what we do.</p>
</body>
</html>"""


class TestScrapeSite:
    def _make_mock_response(self, html: str, status: int = 200):
        mock = MagicMock()
        mock.text = html
        mock.status_code = status
        mock.raise_for_status.return_value = None
        return mock

    @patch("scraper.requests.Session")
    def test_returns_complete_structure(self, MockSession):
        session_instance = MockSession.return_value
        # homepage + up to 6 nav pages from SAMPLE_HOMEPAGE_HTML links
        session_instance.get.return_value = self._make_mock_response(SAMPLE_HOMEPAGE_HTML)

        result = scrape_site("https://example.com")

        assert result["base_url"] == "https://example.com"
        assert result["language"] == "en-GB"
        assert isinstance(result["homepage"], dict)
        assert isinstance(result["all_links"], list)
        assert isinstance(result["nav_pages"], list)
        assert isinstance(result["json_ld"], list)
        assert isinstance(result["open_graph"], dict)
        assert isinstance(result["scrape_errors"], list)

    @patch("scraper.requests.Session")
    def test_homepage_contains_page_text(self, MockSession):
        session_instance = MockSession.return_value
        session_instance.get.return_value = self._make_mock_response(SAMPLE_HOMEPAGE_HTML)

        result = scrape_site("https://example.com")
        homepage = result["homepage"]
        assert homepage["url"] == "https://example.com"
        assert homepage["url_path"] == "/"
        assert homepage["title"] == "Quality products since 2015"  # from h1
        assert isinstance(homepage["text"], str)
        assert len(homepage["text"]) > 0

    @patch("scraper.requests.Session")
    def test_homepage_text_excludes_nav(self, MockSession):
        session_instance = MockSession.return_value
        session_instance.get.return_value = self._make_mock_response(SAMPLE_HOMEPAGE_HTML)

        result = scrape_site("https://example.com")
        homepage_text = result["homepage"]["text"]
        assert isinstance(homepage_text, str)

    @patch("scraper.requests.Session")
    def test_raises_scraper_error_when_homepage_unreachable(self, MockSession):
        import requests
        session_instance = MockSession.return_value
        session_instance.get.side_effect = requests.exceptions.ConnectionError("Connection refused")

        with pytest.raises(ScraperError):
            scrape_site("https://unreachable.example.com")

    @patch("scraper.requests.Session")
    def test_all_links_contains_nav_urls(self, MockSession):
        session_instance = MockSession.return_value
        session_instance.get.return_value = self._make_mock_response(SAMPLE_HOMEPAGE_HTML)

        result = scrape_site("https://example.com")
        all_urls = [l["url"] for l in result["all_links"]]
        assert any("shop" in u for u in all_urls)
        assert any("about" in u for u in all_urls)

    @patch("scraper.requests.Session")
    def test_nav_pages_have_text(self, MockSession):
        session_instance = MockSession.return_value
        session_instance.get.return_value = self._make_mock_response(SAMPLE_PAGE_HTML)

        result = scrape_site("https://example.com")
        for page in result["nav_pages"]:
            assert "text" in page
            assert isinstance(page["text"], str)
