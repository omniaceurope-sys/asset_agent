"""
google_ads_assets.py — Main orchestrator for the Ad Asset Builder Agent.

Usage:
    python scripts/google_ads_assets.py --url https://example.com --account-id 123-456-7890
    python scripts/google_ads_assets.py           # prompts for missing args

Requires:
    - config/google_ads.yaml   (filled in with real credentials)
    - config/accounts.yaml     (account ID → name mapping)
    - ANTHROPIC_API_KEY        (environment variable)

Install deps:
    pip install requests beautifulsoup4 lxml anthropic google-ads pyyaml
"""

import argparse
import json
import re
import sys
from pathlib import Path

import anthropic
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CONFIG_DIR = Path(__file__).parent.parent / "config"
GOOGLE_ADS_YAML = CONFIG_DIR / "google_ads.yaml"
ACCOUNTS_YAML = CONFIG_DIR / "accounts.yaml"

# ---------------------------------------------------------------------------
# Character limits (hard limits per Google Ads policy)
# ---------------------------------------------------------------------------

CHAR_LIMITS = {
    "sitelink_title": 25,
    "sitelink_desc": 35,
    "callout": 25,
    "snippet_value": 25,
}

# ---------------------------------------------------------------------------
# Valid structured snippet headers (English — Google's fixed list)
# ---------------------------------------------------------------------------

SNIPPET_HEADERS_EN = [
    "Amenities",
    "Brands",
    "Courses",
    "Degree programs",
    "Destinations",
    "Featured hotels",
    "Insurance coverage",
    "Models",
    "Neighborhoods",
    "Service catalog",
    "Shows",
    "Styles",
    "Types",
]

# ---------------------------------------------------------------------------
# Claude system prompt (static — cached by Anthropic API)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a Google Ads asset specialist. Given a website URL and account name,
you fetch the site, identify its product/service category structure, and generate
Google Ads sitelinks, callouts, and structured snippets.

STEP 1 — FETCH AND ANALYZE
Use the fetch_url tool to fetch the homepage. Read the page content and ALL links.
Identify CATEGORY pages — pages that list multiple products or services under a theme.
Category pages typically have URL patterns like:
  /product-category/..., /category/..., /collections/..., /shop/..., /kategorija/...,
  /kategorie/..., /categorie/..., or any path that groups products by type.

For sitelinks, ONLY use category pages. NEVER use individual product pages.
Individual product pages have URL patterns like:
  /product/..., /izdelek/..., /produkt/..., /produit/..., /item/..., /p/...,
  or any path that leads to a single specific product.

If you cannot tell from the URL, use fetch_url on the page — a category page shows
a grid or list of multiple products; a product page shows one product with price/add-to-cart.

Also exclude from sitelinks:
  - About us, Contact, FAQ, Blog, News, Press, Careers, Team
  - Delivery, Shipping, Returns, Privacy policy, Terms, Cookie policy
  - Login, Account, Wishlist, Cart
  - Promotional or seasonal campaign landing pages

Use fetch_url on 2–4 category pages to understand what each category contains.

STEP 2 — GENERATE ASSETS
Using ONLY URLs found on the site, generate the assets below.

HARD CHARACTER LIMITS — count every character including spaces. NEVER exceed:
  - Sitelink title:       25 characters
  - Sitelink description: 35 characters (each line)
  - Callout text:         25 characters
  - Snippet value:        25 characters

STRUCTURED SNIPPET HEADERS — use ONLY from this exact list:
  Amenities, Brands, Courses, Degree programs, Destinations, Featured hotels,
  Insurance coverage, Models, Neighborhoods, Service catalog, Shows, Styles, Types

WRITING RULES:
1. Count every character before finalizing. Shorten if needed.
2. Write ALL text in the same language as the website.
3. Only include claims supported by the actual page content.
4. No exclamation marks in sitelink titles or callouts.
5. Title Case for sitelink titles and callout texts.
6. Each callout must communicate a different benefit.
7. ALL sitelinks must link to category pages only — never to individual products.
8. Sitelink descriptions must describe the product/category — not policies or company info.
9. Provide 8–12 sitelinks, 8–12 callouts, and 3–5 structured snippets.

OUTPUT FORMAT:
When done, respond ONLY with valid JSON. No markdown, no explanation.
{
  "sitelinks": [
    {
      "title": "string <= 25 chars",
      "description1": "string <= 35 chars",
      "description2": "string <= 35 chars",
      "final_url": "https://..."
    }
  ],
  "callouts": ["string <= 25 chars"],
  "structured_snippets": [
    {
      "header": "one of the approved headers",
      "values": ["string <= 25 chars"]
    }
  ]
}
"""

# Tool definition for Claude to fetch URLs
FETCH_URL_TOOL = {
    "name": "fetch_url",
    "description": (
        "Fetch the text content of a URL. Returns cleaned page text and all links "
        "found on the page as 'text → url' pairs. Use this to read website pages."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The full URL to fetch (must start with http:// or https://)",
            }
        },
        "required": ["url"],
    },
}


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and push Google Ads assets from a website."
    )
    parser.add_argument("--url", type=str, help="Website URL to scrape")
    parser.add_argument("--account-id", type=str, dest="account_id",
                        help="Google Ads client account ID")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_google_ads_config(path: Path = GOOGLE_ADS_YAML) -> dict:
    """Load google_ads.yaml. Hard exits with a clear message if missing."""
    if not path.exists():
        sys.exit(
            f"ERROR: Google Ads config not found at {path}\n"
            "Copy config/google_ads.yaml and fill in your credentials."
        )
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_accounts_config(path: Path = ACCOUNTS_YAML) -> dict:
    """
    Load accounts.yaml. Returns an empty dict on failure (non-fatal).
    Keys are digit-only account IDs.
    """
    if not path.exists():
        print(f"WARNING: accounts.yaml not found at {path}. Account names will not be shown.",
              file=sys.stderr)
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("accounts", {}) if data else {}
    except yaml.YAMLError as e:
        print(f"WARNING: Could not parse accounts.yaml: {e}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# Account ID normalization
# ---------------------------------------------------------------------------

def normalize_account_id(raw_id: str) -> str:
    """Strip all non-digit characters. '123-456-7890' → '1234567890'"""
    return re.sub(r"\D", "", raw_id)


# ---------------------------------------------------------------------------
# fetch_url tool — executed by Python when Claude calls it
# ---------------------------------------------------------------------------

def _execute_fetch_url(url: str) -> str:
    """
    Fetch a URL and return cleaned text + link list for Claude.
    This is called whenever Claude uses the fetch_url tool.
    """
    import copy as _copy
    import requests as _requests
    from bs4 import BeautifulSoup as _BS
    from urllib.parse import urljoin as _urljoin, urlparse as _urlparse

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AssetBuilderBot/1.0)",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }
    try:
        resp = _requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        return f"ERROR fetching {url}: {e}"

    soup = _BS(resp.text, "lxml")

    # Clean body text
    soup_copy = _copy.copy(soup)
    for tag in soup_copy(["nav", "header", "footer", "script", "style",
                           "aside", "noscript", "svg", "iframe"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup_copy.get_text(" ", strip=True)).strip()[:5000]

    # All internal links
    base = f"{_urlparse(url).scheme}://{_urlparse(url).netloc}"
    seen: set[str] = set()
    link_lines = []
    for a in soup.find_all("a", href=True):
        abs_url = _urljoin(url, a["href"]).split("?")[0].split("#")[0].rstrip("/")
        if abs_url in seen or base not in abs_url:
            continue
        seen.add(abs_url)
        link_text = a.get_text(strip=True) or (a.find("img") or {}).get("alt", "") or ""
        if link_text:
            link_lines.append(f"  {link_text[:60]} → {abs_url}")

    links_block = "\n".join(link_lines[:80]) or "  (no internal links found)"
    return f"PAGE TEXT:\n{text}\n\nINTERNAL LINKS:\n{links_block}"


# ---------------------------------------------------------------------------
# Claude asset generation (agentic — Claude fetches the site itself)
# ---------------------------------------------------------------------------

def generate_assets_with_claude(url: str, account_name: str) -> dict:
    """
    Give Claude the URL and let it fetch and analyze the site using the
    fetch_url tool, then generate ad assets.
    Returns {"sitelinks": [...], "callouts": [...], "structured_snippets": [...]}.
    """
    client = anthropic.Anthropic()

    messages = [
        {
            "role": "user",
            "content": (
                f"Account: {account_name}\n"
                f"Website: {url}\n\n"
                "Fetch this website, identify its product/category structure, "
                "and generate the Google Ads assets."
            ),
        }
    ]

    MAX_TOOL_ROUNDS = 8
    for round_num in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=[{"type": "text", "text": SYSTEM_PROMPT,
                      "cache_control": {"type": "ephemeral"}}],
            tools=[FETCH_URL_TOOL],
            messages=messages,
        )

        # Claude is done — extract JSON from the final text block
        if response.stop_reason == "end_turn":
            for block in response.content:
                if block.type == "text":
                    raw = block.text.strip()
                    # Try fenced code block anywhere in the text
                    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
                    if fence_match:
                        raw = fence_match.group(1).strip()
                    else:
                        # Fall back to first top-level JSON object in the text
                        obj_match = re.search(r"\{[\s\S]*\}", raw)
                        if obj_match:
                            raw = obj_match.group(0)
                    try:
                        assets = json.loads(raw)
                        for key in ("sitelinks", "callouts", "structured_snippets"):
                            assets.setdefault(key, [])
                        return assets
                    except json.JSONDecodeError:
                        continue
            sys.exit("ERROR: Claude finished without returning valid JSON assets.")

        # Claude called fetch_url — execute it and return results
        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use" and block.name == "fetch_url":
                    fetch_url = block.input.get("url", "")
                    result = _execute_fetch_url(fetch_url)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        break  # unexpected stop reason

    sys.exit("ERROR: Claude did not finish within the allowed tool call rounds.")


# ---------------------------------------------------------------------------
# Asset validation (character limits)
# ---------------------------------------------------------------------------

def _trim_to_limit(text: str, limit: int) -> str | None:
    """
    Trim text to fit within limit characters at a word boundary.
    Returns None if trimming produces an empty string.
    """
    if len(text) <= limit:
        return text
    trimmed = text[:limit]
    # Walk back to last space
    last_space = trimmed.rfind(" ")
    if last_space > 0:
        trimmed = trimmed[:last_space]
    trimmed = trimmed.strip()
    return trimmed if trimmed else None


def validate_assets(assets: dict) -> tuple[dict, list[str]]:
    """
    Enforce character limits on all generated assets.
    Trims at word boundary; drops asset if untrimable.
    Returns (cleaned_assets, list_of_warnings).
    """
    warnings = []
    cleaned = {"sitelinks": [], "callouts": [], "structured_snippets": []}

    # --- Sitelinks ---
    for sl in assets.get("sitelinks", []):
        ok = True
        for field, limit_key in [
            ("title", "sitelink_title"),
            ("description1", "sitelink_desc"),
            ("description2", "sitelink_desc"),
        ]:
            val = sl.get(field, "")
            limit = CHAR_LIMITS[limit_key]
            if len(val) > limit:
                trimmed = _trim_to_limit(val, limit)
                if trimmed is None:
                    warnings.append(
                        f"Sitelink dropped — {field} could not be trimmed: '{val}'"
                    )
                    ok = False
                    break
                warnings.append(
                    f"Sitelink '{sl.get('title', '')}' {field} trimmed: "
                    f"'{val}' → '{trimmed}'"
                )
                sl[field] = trimmed
        if ok and sl.get("title") and sl.get("final_url"):
            cleaned["sitelinks"].append(sl)

    # --- Callouts ---
    limit = CHAR_LIMITS["callout"]
    for text in assets.get("callouts", []):
        if len(text) <= limit:
            cleaned["callouts"].append(text)
        else:
            trimmed = _trim_to_limit(text, limit)
            if trimmed:
                warnings.append(f"Callout trimmed: '{text}' → '{trimmed}'")
                cleaned["callouts"].append(trimmed)
            else:
                warnings.append(f"Callout dropped — could not trim: '{text}'")

    # --- Structured snippets ---
    limit = CHAR_LIMITS["snippet_value"]
    for snippet in assets.get("structured_snippets", []):
        valid_values = []
        for val in snippet.get("values", []):
            if len(val) <= limit:
                valid_values.append(val)
            else:
                trimmed = _trim_to_limit(val, limit)
                if trimmed:
                    warnings.append(
                        f"Snippet value trimmed: '{val}' → '{trimmed}'"
                    )
                    valid_values.append(trimmed)
                else:
                    warnings.append(f"Snippet value dropped — could not trim: '{val}'")
        if valid_values and snippet.get("header"):
            cleaned["structured_snippets"].append({
                "header": snippet["header"],
                "values": valid_values,
            })

    return cleaned, warnings


# ---------------------------------------------------------------------------
# Google Ads client
# ---------------------------------------------------------------------------

def init_google_ads_client(config_path: Path = GOOGLE_ADS_YAML):
    """
    Initialize GoogleAdsClient from config file.
    Exits with a clear message on failure.
    """
    try:
        from google.ads.googleads.client import GoogleAdsClient  # noqa: PLC0415
        return GoogleAdsClient.load_from_storage(str(config_path))
    except Exception as e:
        sys.exit(
            f"ERROR: Could not initialize Google Ads client — {e}\n"
            f"Check your credentials in {config_path}"
        )


def init_google_ads_client_from_dict(credentials: dict):
    """
    Initialize GoogleAdsClient from a credentials dict.
    Used by the Streamlit UI (credentials come from st.secrets, not a file).
    Raises RuntimeError on failure (does not sys.exit — caller handles it).
    """
    try:
        from google.ads.googleads.client import GoogleAdsClient  # noqa: PLC0415
        return GoogleAdsClient.load_from_dict(credentials)
    except Exception as e:
        raise RuntimeError(f"Could not initialize Google Ads client: {e}") from e


def list_child_accounts(client, mcc_id: str) -> list[dict]:
    """
    Return all enabled non-manager (leaf) accounts under the MCC.

    Each dict: {"id": str, "name": str, "currency": str, "timezone": str}
    Sorted alphabetically by name.
    Raises RuntimeError if the API query fails.
    """
    ga_service = client.get_service("GoogleAdsService")
    query = """
        SELECT
            customer_client.id,
            customer_client.descriptive_name,
            customer_client.currency_code,
            customer_client.time_zone,
            customer_client.manager,
            customer_client.status
        FROM customer_client
        WHERE customer_client.manager = false
          AND customer_client.status = 'ENABLED'
    """
    accounts = []
    try:
        stream = ga_service.search_stream(customer_id=mcc_id, query=query)
        for batch in stream:
            for row in batch.results:
                cc = row.customer_client
                accounts.append({
                    "id": str(cc.id),
                    "name": cc.descriptive_name or f"Account {cc.id}",
                    "currency": cc.currency_code,
                    "timezone": cc.time_zone,
                })
    except Exception as e:
        raise RuntimeError(f"Could not list child accounts: {e}") from e
    return sorted(accounts, key=lambda x: x["name"].lower())


# ---------------------------------------------------------------------------
# Fetch existing assets (duplicate detection)
# ---------------------------------------------------------------------------

def fetch_existing_assets(client, customer_id: str) -> dict:
    """
    Query the account for existing sitelinks, callouts, and structured snippets.
    Returns sets of lowercased strings for comparison.
    """
    ga_service = client.get_service("GoogleAdsService")
    existing = {
        "sitelink_titles": set(),
        "callout_texts": set(),
        "snippet_headers": set(),
    }

    queries = {
        "sitelink_titles": (
            "SELECT asset.sitelink_asset.link_text FROM asset "
            "WHERE asset.type = 'SITELINK'"
        ),
        "callout_texts": (
            "SELECT asset.callout_asset.callout_text FROM asset "
            "WHERE asset.type = 'CALLOUT'"
        ),
        "snippet_headers": (
            "SELECT asset.structured_snippet_asset.header FROM asset "
            "WHERE asset.type = 'STRUCTURED_SNIPPET'"
        ),
    }

    for key, query in queries.items():
        try:
            stream = ga_service.search_stream(customer_id=customer_id, query=query)
            for batch in stream:
                for row in batch.results:
                    asset = row.asset
                    if key == "sitelink_titles":
                        text = asset.sitelink_asset.link_text
                    elif key == "callout_texts":
                        text = asset.callout_asset.callout_text
                    else:
                        text = asset.structured_snippet_asset.header
                    if text:
                        existing[key].add(text.lower())
        except Exception as e:
            print(f"  WARNING: Could not fetch existing {key}: {e}", file=sys.stderr)

    print(
        f"\nChecking existing assets in account...\n"
        f"  Existing sitelinks: {len(existing['sitelink_titles'])}\n"
        f"  Existing callouts:  {len(existing['callout_texts'])}\n"
        f"  Existing snippets:  {len(existing['snippet_headers'])}"
    )
    return existing


# ---------------------------------------------------------------------------
# Asset operation builders
# ---------------------------------------------------------------------------

def _build_sitelink_operation(client, sl: dict):
    """Build an AssetOperation for a sitelink."""
    op = client.get_type("AssetOperation")
    asset = op.create
    asset.sitelink_asset.link_text = sl["title"]
    asset.sitelink_asset.description1 = sl.get("description1", "")
    asset.sitelink_asset.description2 = sl.get("description2", "")
    asset.final_urls.append(sl["final_url"])
    return op


def _build_callout_operation(client, text: str):
    """Build an AssetOperation for a callout."""
    op = client.get_type("AssetOperation")
    op.create.callout_asset.callout_text = text
    return op


def _build_snippet_operation(client, snippet: dict):
    """Build an AssetOperation for a structured snippet."""
    op = client.get_type("AssetOperation")
    asset = op.create
    asset.structured_snippet_asset.header = snippet["header"]
    asset.structured_snippet_asset.values.extend(snippet["values"])
    return op


# ---------------------------------------------------------------------------
# Push helpers
# ---------------------------------------------------------------------------

def _parse_partial_failures(response, operations: list) -> set[int]:
    """
    Return the set of operation indices that failed (from partial_failure_error).
    """
    failed_indices = set()
    pfe = response.partial_failure_error
    if not pfe or not pfe.details:
        return failed_indices
    from google.ads.googleads.errors import GoogleAdsException  # noqa: PLC0415
    try:
        from google.ads.googleads.v17.errors.types.errors import (  # noqa: PLC0415
            GoogleAdsFailure,
        )
        from google.protobuf import any_pb2  # noqa: PLC0415
        for detail in pfe.details:
            failure = GoogleAdsFailure()
            detail.Unpack(failure)
            for error in failure.errors:
                loc = error.location
                if loc and loc.field_path_elements:
                    idx = loc.field_path_elements[0].index
                    failed_indices.add(idx)
    except Exception:
        # If we can't parse partial failures precisely, assume all failed
        failed_indices = set(range(len(operations)))
    return failed_indices


def push_sitelinks(client, customer_id: str, sitelinks: list[dict], existing: dict) -> dict:
    """
    Push sitelinks to Google Ads. Skips duplicates, uses partial failure mode.
    Prints ✓/⊘/✗ per asset. Returns summary dict.
    """
    print("\nCreating sitelinks...")
    asset_service = client.get_service("AssetService")

    to_create = []
    skipped = 0
    for sl in sitelinks:
        if sl["title"].lower() in existing["sitelink_titles"]:
            print(f"  ⊘ {sl['title']} (already exists)")
            skipped += 1
        else:
            to_create.append(sl)

    if not to_create:
        print(f"  Created: 0 / Skipped: {skipped} / Failed: 0")
        return {"created": 0, "skipped": skipped, "failed": 0, "failed_items": []}

    operations = [_build_sitelink_operation(client, sl) for sl in to_create]
    created = 0
    failed = 0
    failed_items = []

    try:
        response = asset_service.mutate_assets(
            customer_id=customer_id,
            operations=operations,
            partial_failure=True,
        )
        failed_indices = _parse_partial_failures(response, operations)
        for i, sl in enumerate(to_create):
            if i in failed_indices:
                print(f"  ✗ {sl['title']} (API rejected)")
                failed += 1
                failed_items.append(sl["title"])
            else:
                print(f"  ✓ {sl['title']} → {sl['final_url']}")
                created += 1
    except Exception as e:
        print(f"  ✗ All sitelinks failed — {e}", file=sys.stderr)
        failed = len(to_create)
        failed_items = [sl["title"] for sl in to_create]

    print(f"  Created: {created} / Skipped: {skipped} / Failed: {failed}")
    return {"created": created, "skipped": skipped, "failed": failed, "failed_items": failed_items}


def push_callouts(client, customer_id: str, callouts: list[str], existing: dict) -> dict:
    """Push callouts to Google Ads."""
    print("\nCreating callouts...")
    asset_service = client.get_service("AssetService")

    to_create = []
    skipped = 0
    for text in callouts:
        if text.lower() in existing["callout_texts"]:
            print(f"  ⊘ {text} (already exists)")
            skipped += 1
        else:
            to_create.append(text)

    if not to_create:
        print(f"  Created: 0 / Skipped: {skipped} / Failed: 0")
        return {"created": 0, "skipped": skipped, "failed": 0, "failed_items": []}

    operations = [_build_callout_operation(client, text) for text in to_create]
    created = 0
    failed = 0
    failed_items = []

    try:
        response = asset_service.mutate_assets(
            customer_id=customer_id,
            operations=operations,
            partial_failure=True,
        )
        failed_indices = _parse_partial_failures(response, operations)
        for i, text in enumerate(to_create):
            if i in failed_indices:
                print(f"  ✗ {text} (API rejected)")
                failed += 1
                failed_items.append(text)
            else:
                print(f"  ✓ {text}")
                created += 1
    except Exception as e:
        print(f"  ✗ All callouts failed — {e}", file=sys.stderr)
        failed = len(to_create)
        failed_items = list(to_create)

    print(f"  Created: {created} / Skipped: {skipped} / Failed: {failed}")
    return {"created": created, "skipped": skipped, "failed": failed, "failed_items": failed_items}


def push_structured_snippets(client, customer_id: str, snippets: list[dict], existing: dict) -> dict:
    """Push structured snippets to Google Ads."""
    print("\nCreating structured snippets...")
    asset_service = client.get_service("AssetService")

    to_create = []
    skipped = 0
    for snippet in snippets:
        if snippet["header"].lower() in existing["snippet_headers"]:
            print(f"  ⊘ {snippet['header']} (already exists)")
            skipped += 1
        else:
            to_create.append(snippet)

    if not to_create:
        print(f"  Created: 0 / Skipped: {skipped} / Failed: 0")
        return {"created": 0, "skipped": skipped, "failed": 0, "failed_items": []}

    operations = [_build_snippet_operation(client, s) for s in to_create]
    created = 0
    failed = 0
    failed_items = []

    try:
        response = asset_service.mutate_assets(
            customer_id=customer_id,
            operations=operations,
            partial_failure=True,
        )
        failed_indices = _parse_partial_failures(response, operations)
        for i, snippet in enumerate(to_create):
            if i in failed_indices:
                print(f"  ✗ {snippet['header']} (API rejected)")
                failed += 1
                failed_items.append(snippet["header"])
            else:
                values_str = ", ".join(snippet["values"])
                print(f"  ✓ {snippet['header']}: {values_str}")
                created += 1
    except Exception as e:
        print(f"  ✗ All structured snippets failed — {e}", file=sys.stderr)
        failed = len(to_create)
        failed_items = [s["header"] for s in to_create]

    print(f"  Created: {created} / Skipped: {skipped} / Failed: {failed}")
    return {"created": created, "skipped": skipped, "failed": failed, "failed_items": failed_items}


# ---------------------------------------------------------------------------
# Fallback output (when Google Ads API is completely unavailable)
# ---------------------------------------------------------------------------

def print_fallback_assets(assets: dict) -> None:
    """Print all generated assets to stdout for manual creation."""
    print("\n" + "=" * 60)
    print("! Google Ads API unavailable. Assets for manual creation:")
    print("=" * 60)

    print("\nSITELINKS:")
    for sl in assets.get("sitelinks", []):
        print(f"  Title ({len(sl['title'])}):  {sl['title']}")
        print(f"  Desc1 ({len(sl.get('description1',''))}):  {sl.get('description1','')}")
        print(f"  Desc2 ({len(sl.get('description2',''))}):  {sl.get('description2','')}")
        print(f"  URL:   {sl.get('final_url','')}")
        print("  ---")

    print("\nCALLOUTS:")
    for text in assets.get("callouts", []):
        print(f"  {text}  ({len(text)} chars)")

    print("\nSTRUCTURED SNIPPETS:")
    for snippet in assets.get("structured_snippets", []):
        values_str = ", ".join(snippet.get("values", []))
        print(f"  {snippet['header']}: {values_str}")

    print("=" * 60)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(
    account_id: str,
    account_name: str,
    results: dict,
) -> None:
    """Print the final run summary and reminder."""
    sl = results.get("sitelinks", {})
    co = results.get("callouts", {})
    sn = results.get("structured_snippets", {})

    total_created = (
        sl.get("created", 0) + co.get("created", 0) + sn.get("created", 0)
    )
    all_failed = []
    all_failed.extend(sl.get("failed_items", []))
    all_failed.extend(co.get("failed_items", []))
    all_failed.extend(sn.get("failed_items", []))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print(f"  Account:            {account_id} ({account_name})")
    print(f"  Sitelinks:          {sl.get('created',0)} created, "
          f"{sl.get('skipped',0)} skipped, {sl.get('failed',0)} failed")
    print(f"  Callouts:           {co.get('created',0)} created, "
          f"{co.get('skipped',0)} skipped, {co.get('failed',0)} failed")
    print(f"  Structured Snippets:{sn.get('created',0)} created, "
          f"{sn.get('skipped',0)} skipped, {sn.get('failed',0)} failed")
    print(f"  Total assets created: {total_created}")
    if all_failed:
        print(f"  Failures: {', '.join(all_failed)}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    # --- Load configs ---
    ads_config = load_google_ads_config()
    accounts = load_accounts_config()

    # --- Resolve account ID ---
    raw_account_id = args.account_id
    if not raw_account_id:
        raw_account_id = input("Enter Google Ads account ID: ").strip()

    account_id = normalize_account_id(raw_account_id)
    account_name = accounts.get(account_id, {}).get("name", account_id) if accounts else account_id

    print(f"\nAccount: {account_id} ({account_name})")

    # --- Resolve URL ---
    url = args.url
    if not url:
        url = input("Enter website URL: ").strip()

    # --- Scrape ---
    scraped_data = run_scraper(url)

    # --- Generate assets with Claude ---
    raw_assets = generate_assets_with_claude(scraped_data, account_name)

    # --- Validate character limits ---
    assets, warnings = validate_assets(raw_assets)
    if warnings:
        print("\nValidation warnings:")
        for w in warnings:
            print(f"  ⚠ {w}")

    # --- Connect to Google Ads ---
    try:
        client = init_google_ads_client()
        existing = fetch_existing_assets(client, account_id)

        sl_result = push_sitelinks(client, account_id, assets["sitelinks"], existing)
        co_result = push_callouts(client, account_id, assets["callouts"], existing)
        sn_result = push_structured_snippets(client, account_id, assets["structured_snippets"], existing)

        print_summary(account_id, account_name, {
            "sitelinks": sl_result,
            "callouts": co_result,
            "structured_snippets": sn_result,
        })

    except SystemExit:
        # Google Ads init failed — fall back to printing assets
        print_fallback_assets(assets)
        raise


if __name__ == "__main__":
    main()
