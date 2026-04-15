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
    _extract_body_excerpt,
    _extract_brand_name,
    _extract_currency,
    _extract_json_ld,
    _extract_language,
    _extract_nav_links,
    _extract_open_graph,
    _extract_tagline,
    _extract_trust_signals,
    _fetch,
    _find_secondary_pages,
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
# _extract_brand_name
# ===========================================================================

class TestExtractBrandName:
    def test_prefers_og_site_name(self):
        html = '''<html><head>
        <meta property="og:site_name" content="BrandFromOG">
        <title>SomeOtherTitle</title>
        </head></html>'''
        soup = make_soup(html)
        assert _extract_brand_name(soup, []) == "BrandFromOG"

    def test_falls_back_to_json_ld_organization(self):
        html = "<html><head><title>Page | Shop</title></head></html>"
        json_ld = [{"@type": "Organization", "name": "OrgName"}]
        assert _extract_brand_name(make_soup(html), json_ld) == "OrgName"

    def test_falls_back_to_title_stripped(self):
        html = "<html><head><title>BrandName | Home</title></head></html>"
        assert _extract_brand_name(make_soup(html), []) == "BrandName"

    def test_strips_title_dash_separator(self):
        html = "<html><head><title>My Brand - Official Site</title></head></html>"
        assert _extract_brand_name(make_soup(html), []) == "My Brand"

    def test_strips_title_endash_separator(self):
        html = "<html><head><title>My Shop – Great Deals</title></head></html>"
        assert _extract_brand_name(make_soup(html), []) == "My Shop"

    def test_json_ld_graph_format(self):
        html = "<html><head></head></html>"
        json_ld = [{"@graph": [{"@type": "WebSite", "name": "GraphBrand"}]}]
        assert _extract_brand_name(make_soup(html), json_ld) == "GraphBrand"

    def test_returns_none_when_nothing_found(self):
        html = "<html><head></head><body></body></html>"
        assert _extract_brand_name(make_soup(html), []) is None


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
# _extract_currency
# ===========================================================================

class TestExtractCurrency:
    def test_reads_og_price_currency(self):
        html = '<html><head><meta property="og:price:currency" content="GBP"></head></html>'
        assert _extract_currency(make_soup(html), []) == "GBP"

    def test_reads_product_price_currency(self):
        html = '<html><head><meta property="product:price:currency" content="EUR"></head></html>'
        assert _extract_currency(make_soup(html), []) == "EUR"

    def test_reads_json_ld_offers(self):
        html = "<html><head></head></html>"
        json_ld = [{"@type": "Product", "offers": {"priceCurrency": "USD"}}]
        assert _extract_currency(make_soup(html), json_ld) == "USD"

    def test_detects_pound_symbol(self):
        html = "<html><body><p>Price: £29.99</p></body></html>"
        assert _extract_currency(make_soup(html), []) == "GBP"

    def test_detects_euro_symbol(self):
        html = "<html><body><p>Preis: €19.99</p></body></html>"
        assert _extract_currency(make_soup(html), []) == "EUR"

    def test_detects_dollar_symbol(self):
        html = "<html><body><p>Price: $49.99</p></body></html>"
        assert _extract_currency(make_soup(html), []) == "USD"

    def test_returns_none_when_no_currency(self):
        html = "<html><body><p>No prices here</p></body></html>"
        assert _extract_currency(make_soup(html), []) is None


# ===========================================================================
# _extract_tagline
# ===========================================================================

class TestExtractTagline:
    def test_reads_h1(self):
        html = "<html><body><h1>Our Amazing Products</h1></body></html>"
        assert _extract_tagline(make_soup(html)) == "Our Amazing Products"

    def test_falls_back_to_og_description(self):
        html = '''<html>
        <head><meta property="og:description" content="Best shop online"></head>
        <body></body></html>'''
        assert _extract_tagline(make_soup(html)) == "Best shop online"

    def test_falls_back_to_meta_description(self):
        html = '''<html>
        <head><meta name="description" content="Quality products since 2010"></head>
        <body></body></html>'''
        assert _extract_tagline(make_soup(html)) == "Quality products since 2010"

    def test_returns_none_when_nothing(self):
        html = "<html><head></head><body><p>Just a paragraph</p></body></html>"
        assert _extract_tagline(make_soup(html)) is None

    def test_ignores_very_long_h1(self):
        long_text = "x" * 201
        html = f"<html><body><h1>{long_text}</h1><meta name='description' content='short'></body></html>"
        result = _extract_tagline(make_soup(html))
        # Should fall back since h1 is > 200 chars
        assert result is None or len(result) <= 200


# ===========================================================================
# _extract_trust_signals
# ===========================================================================

class TestExtractTrustSignals:
    def test_detects_free_shipping(self):
        html = "<html><body><p>Enjoy free shipping on all orders.</p></body></html>"
        signals = _extract_trust_signals(make_soup(html), [])
        assert any("Free Shipping" in s for s in signals)

    def test_detects_money_back_guarantee(self):
        html = "<html><body><p>30-day money-back guarantee.</p></body></html>"
        signals = _extract_trust_signals(make_soup(html), [])
        assert any("Money-Back Guarantee" in s for s in signals)

    def test_detects_star_rating(self):
        html = "<html><body><p>Rated 4.8/5 star by our customers.</p></body></html>"
        signals = _extract_trust_signals(make_soup(html), [])
        assert any("Star Rating" in s for s in signals)

    def test_detects_email(self):
        html = "<html><body><p>Contact us at hello@example.com</p></body></html>"
        signals = _extract_trust_signals(make_soup(html), [])
        assert any("hello@example.com" in s for s in signals)

    def test_detects_years_in_business(self):
        html = "<html><body><p>Trusted since 2010.</p></body></html>"
        signals = _extract_trust_signals(make_soup(html), [])
        assert any("Years in Business" in s for s in signals)

    def test_extracts_address_from_json_ld(self):
        html = "<html><body></body></html>"
        json_ld = [{
            "@type": "LocalBusiness",
            "address": {
                "streetAddress": "123 Main St",
                "addressLocality": "London",
                "addressCountry": "GB",
            }
        }]
        signals = _extract_trust_signals(make_soup(html), json_ld)
        assert any("London" in s for s in signals)

    def test_deduplicates_signals(self):
        html = "<html><body><p>free shipping free shipping free shipping</p></body></html>"
        signals = _extract_trust_signals(make_soup(html), [])
        free_shipping = [s for s in signals if "Free Shipping" in s]
        assert len(free_shipping) <= 1

    def test_empty_page_returns_empty_list(self):
        html = "<html><body></body></html>"
        assert _extract_trust_signals(make_soup(html), []) == []


# ===========================================================================
# _extract_nav_links
# ===========================================================================

class TestExtractNavLinks:
    BASE = "https://example.com"

    def test_extracts_nav_links(self):
        html = '''<html><body>
        <nav>
          <a href="/shop">Shop</a>
          <a href="/about">About</a>
        </nav>
        </body></html>'''
        links = _extract_nav_links(make_soup(html), self.BASE)
        urls = [l["url"] for l in links]
        assert "https://example.com/shop" in urls
        assert "https://example.com/about" in urls

    def test_excludes_homepage_link(self):
        html = '''<html><body>
        <nav>
          <a href="/">Home</a>
          <a href="/shop">Shop</a>
        </nav>
        </body></html>'''
        links = _extract_nav_links(make_soup(html), self.BASE)
        urls = [l["url"] for l in links]
        assert self.BASE not in urls
        assert "https://example.com/shop" in urls

    def test_excludes_external_links(self):
        html = '''<html><body>
        <nav>
          <a href="https://external.com/page">External</a>
          <a href="/internal">Internal</a>
        </nav>
        </body></html>'''
        links = _extract_nav_links(make_soup(html), self.BASE)
        urls = [l["url"] for l in links]
        assert "https://external.com/page" not in urls
        assert "https://example.com/internal" in urls

    def test_deduplicates_urls(self):
        html = '''<html><body>
        <nav>
          <a href="/shop">Shop Link 1</a>
          <a href="/shop">Shop Link 2</a>
        </nav>
        </body></html>'''
        links = _extract_nav_links(make_soup(html), self.BASE)
        urls = [l["url"] for l in links]
        assert urls.count("https://example.com/shop") == 1

    def test_skips_links_with_very_long_text(self):
        long_text = "A" * 61
        html = f'''<html><body>
        <nav>
          <a href="/page">{long_text}</a>
          <a href="/short">Short</a>
        </nav>
        </body></html>'''
        links = _extract_nav_links(make_soup(html), self.BASE)
        texts = [l["text"] for l in links]
        assert long_text not in texts
        assert "Short" in texts

    def test_skips_mailto_and_tel(self):
        html = '''<html><body>
        <nav>
          <a href="mailto:hi@example.com">Email</a>
          <a href="tel:123456">Call</a>
          <a href="/shop">Shop</a>
        </nav>
        </body></html>'''
        links = _extract_nav_links(make_soup(html), self.BASE)
        urls = [l["url"] for l in links]
        assert all(u.startswith("https://") for u in urls)


# ===========================================================================
# _find_secondary_pages
# ===========================================================================

class TestFindSecondaryPages:
    BASE = "https://example.com"

    def test_matches_slug_in_path(self):
        links = [
            {"text": "Our Story", "url": "https://example.com/about-us"},
            {"text": "Get in Touch", "url": "https://example.com/contact"},
        ]
        result = _find_secondary_pages(links, self.BASE)
        assert result["about"] == "https://example.com/about-us"
        assert result["contact"] == "https://example.com/contact"

    def test_matches_slug_in_link_text(self):
        links = [
            {"text": "About Us", "url": "https://example.com/company"},
        ]
        result = _find_secondary_pages(links, self.BASE)
        assert result.get("about") == "https://example.com/company"

    def test_first_match_wins(self):
        links = [
            {"text": "About Page 1", "url": "https://example.com/about1"},
            {"text": "About Page 2", "url": "https://example.com/about2"},
        ]
        result = _find_secondary_pages(links, self.BASE)
        assert result.get("about") == "https://example.com/about1"

    def test_returns_empty_when_no_matches(self):
        links = [{"text": "Shop", "url": "https://example.com/shop"}]
        result = _find_secondary_pages(links, self.BASE)
        assert "about" not in result

    def test_matches_shipping_slug(self):
        links = [{"text": "Delivery Info", "url": "https://example.com/shipping-info"}]
        result = _find_secondary_pages(links, self.BASE)
        assert result.get("shipping") == "https://example.com/shipping-info"


# ===========================================================================
# _extract_body_excerpt
# ===========================================================================

class TestExtractBodyExcerpt:
    def test_extracts_first_paragraph(self):
        html = "<html><body><p>This is the first paragraph with enough content.</p></body></html>"
        result = _extract_body_excerpt(make_soup(html))
        assert "first paragraph" in result

    def test_skips_short_paragraphs(self):
        html = "<html><body><p>Short</p><p>This is a longer paragraph with meaningful content here.</p></body></html>"
        result = _extract_body_excerpt(make_soup(html))
        assert "longer paragraph" in result

    def test_combines_up_to_three_paragraphs(self):
        html = """<html><body>
        <p>First paragraph with enough content to be included here.</p>
        <p>Second paragraph with enough content to be included here.</p>
        <p>Third paragraph with enough content to be included here.</p>
        <p>Fourth paragraph that should not appear in excerpt output.</p>
        </body></html>"""
        result = _extract_body_excerpt(make_soup(html))
        assert "First paragraph" in result
        assert "Third paragraph" in result
        assert "Fourth paragraph" not in result

    def test_excludes_footer_content(self):
        html = """<html><body>
        <footer><p>Footer content that should not appear in excerpt text here.</p></footer>
        <main><p>Main content paragraph that is long enough to be included.</p></main>
        </body></html>"""
        result = _extract_body_excerpt(make_soup(html))
        assert "Footer content" not in result

    def test_excludes_nav_content(self):
        html = """<html><body>
        <nav><p>Navigation text with plenty of characters to pass length check.</p></nav>
        <article><p>Article content paragraph that is long enough to be included.</p></article>
        </body></html>"""
        result = _extract_body_excerpt(make_soup(html))
        assert "Navigation text" not in result

    def test_returns_none_when_no_paragraphs(self):
        html = "<html><body><div>No paragraph tags here</div></body></html>"
        assert _extract_body_excerpt(make_soup(html)) is None


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
  <meta property="og:price:currency" content="GBP">
  <script type="application/ld+json">
  {"@type": "Organization", "name": "TestBrand", "address": {"streetAddress": "1 High St", "addressLocality": "London", "addressCountry": "GB"}}
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

    @patch("scraper._is_allowed_by_robots", return_value=True)
    @patch("scraper.requests.Session")
    def test_returns_complete_structure(self, MockSession, mock_robots):
        session_instance = MockSession.return_value
        session_instance.get.return_value = self._make_mock_response(SAMPLE_PAGE_HTML)

        # Homepage call returns SAMPLE_HOMEPAGE_HTML
        session_instance.get.side_effect = [
            self._make_mock_response(SAMPLE_HOMEPAGE_HTML),  # homepage
            self._make_mock_response(SAMPLE_PAGE_HTML),       # /shop
            self._make_mock_response(SAMPLE_PAGE_HTML),       # /about
            self._make_mock_response(SAMPLE_PAGE_HTML),       # /contact
            self._make_mock_response(SAMPLE_PAGE_HTML),       # /shipping
            self._make_mock_response(SAMPLE_PAGE_HTML),       # secondary: about
            self._make_mock_response(SAMPLE_PAGE_HTML),       # secondary: contact
            self._make_mock_response(SAMPLE_PAGE_HTML),       # secondary: shipping
            self._make_mock_response(SAMPLE_PAGE_HTML),       # secondary: returns
            self._make_mock_response(SAMPLE_PAGE_HTML),       # secondary: faq
        ]

        result = scrape_site("https://example.com")

        assert result["base_url"] == "https://example.com"
        assert result["brand_name"] == "TestBrand"
        assert result["language"] == "en-GB"
        assert result["currency"] == "GBP"
        assert isinstance(result["nav_links"], list)
        assert isinstance(result["nav_pages"], list)
        assert isinstance(result["secondary_pages"], dict)
        assert isinstance(result["json_ld"], list)
        assert isinstance(result["open_graph"], dict)
        assert isinstance(result["trust_signals"], list)
        assert isinstance(result["scrape_errors"], list)

    @patch("scraper._is_allowed_by_robots", return_value=True)
    @patch("scraper.requests.Session")
    def test_raises_scraper_error_when_homepage_unreachable(self, MockSession, mock_robots):
        import requests
        session_instance = MockSession.return_value
        session_instance.get.side_effect = requests.exceptions.ConnectionError("Connection refused")

        with pytest.raises(ScraperError):
            scrape_site("https://unreachable.example.com")

    @patch("scraper._is_allowed_by_robots", return_value=True)
    @patch("scraper.requests.Session")
    def test_extracts_trust_signals_from_homepage(self, MockSession, mock_robots):
        session_instance = MockSession.return_value
        # Return homepage HTML for all fetches
        session_instance.get.return_value = self._make_mock_response(SAMPLE_HOMEPAGE_HTML)

        result = scrape_site("https://example.com")
        assert any("Free Shipping" in s for s in result["trust_signals"])

    @patch("scraper._is_allowed_by_robots", return_value=True)
    @patch("scraper.requests.Session")
    def test_detects_nav_links(self, MockSession, mock_robots):
        session_instance = MockSession.return_value
        session_instance.get.return_value = self._make_mock_response(SAMPLE_HOMEPAGE_HTML)

        result = scrape_site("https://example.com")
        nav_urls = [l["url"] for l in result["nav_links"]]
        assert "https://example.com/shop" in nav_urls
        assert "https://example.com/about" in nav_urls
