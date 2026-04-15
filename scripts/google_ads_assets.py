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
You are a Google Ads copywriter specializing in ad asset creation.
You generate sitelinks, callouts, and structured snippets for Google Ads accounts.

HARD CHARACTER LIMITS — count every character including spaces. NEVER exceed:
  - Sitelink title:       25 characters
  - Sitelink description: 35 characters (each line)
  - Callout text:         25 characters
  - Snippet value:        25 characters

STRUCTURED SNIPPET HEADERS — use ONLY from this exact list (copy spelling exactly):
  Amenities, Brands, Courses, Degree programs, Destinations, Featured hotels,
  Insurance coverage, Models, Neighborhoods, Service catalog, Shows, Styles, Types

WRITING RULES:
1. Before finalizing any text, count every character. If it exceeds the limit, shorten it.
2. Write ALL text in the same language as the website (do NOT translate to English).
3. Only include claims that are directly supported by the scraped data provided.
   Never add "Award-Winning", "Best in Class", "Clinically Proven", "#1", etc.
   unless the scraped data explicitly states it.
4. No exclamation marks in sitelink titles or callouts.
   Maximum one exclamation mark allowed in sitelink descriptions.
5. Title Case for sitelink titles and callout texts.
6. Each callout must communicate a different benefit — no redundancy.
7. Do NOT create sitelinks for: the homepage, blog posts, privacy policy,
   terms of service, cookie policy, login, account pages, contact pages,
   support pages, FAQ pages, customer service pages, or any non-product destination.
   ALL sitelinks must link to product pages, category pages, or collection pages only.
8. ALL sitelink descriptions must be strictly product-focused: describe what the
   product is, its key features, materials, or why a shopper would want it.
   Do NOT write descriptions about shipping, returns, company values, contact info,
   customer service, guarantees, or any non-product topic.
9. Only use structured snippet headers that genuinely fit the business.
   Do not force a header that does not apply.
10. Provide 3–10 values per structured snippet.
11. Provide 8–12 sitelinks, 8–12 callouts, and 3–5 structured snippets.

OUTPUT FORMAT:
Respond ONLY with valid JSON. No markdown fences, no explanation, no preamble.
Exact schema:

{
  "sitelinks": [
    {
      "title": "string <= 25 chars",
      "description1": "string <= 35 chars",
      "description2": "string <= 35 chars",
      "final_url": "https://..."
    }
  ],
  "callouts": [
    "string <= 25 chars"
  ],
  "structured_snippets": [
    {
      "header": "one of the approved headers",
      "values": ["string <= 25 chars", "..."]
    }
  ]
}
"""


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
# Scraper wrapper
# ---------------------------------------------------------------------------

def run_scraper(url: str) -> dict:
    """
    Run the scraper and print a progress summary.
    Re-raises ScraperError on unrecoverable failure.
    """
    # Import here so the module can be used independently
    sys.path.insert(0, str(Path(__file__).parent))
    from scraper import scrape_site, ScraperError  # noqa: PLC0415

    print(f"\nScraping {url}...")

    try:
        data = scrape_site(url)
    except ScraperError as e:
        sys.exit(f"ERROR: Scraper failed — {e}")

    brand = data.get("brand_name") or "(unknown brand)"
    lang = data.get("language") or "unknown"
    nav_count = len(data.get("nav_pages", []))
    trust_count = len(data.get("trust_signals", []))
    secondary_found = [k for k, v in data.get("secondary_pages", {}).items() if v is not None]

    print(f"  Brand:         {brand}")
    print(f"  Language:      {lang}")
    print(f"  Nav pages:     {nav_count}")
    print(f"  Trust signals: {trust_count}")
    if secondary_found:
        print(f"  Secondary pages found: {', '.join(secondary_found)}")
    if data.get("scrape_errors"):
        for err in data["scrape_errors"]:
            print(f"  WARNING: {err}", file=sys.stderr)

    return data


# ---------------------------------------------------------------------------
# Claude prompt builder
# ---------------------------------------------------------------------------

def build_user_prompt(scraped_data: dict, account_name: str) -> str:
    """Format scraped data into the Claude user message."""

    def fmt_page(page: dict) -> str:
        lines = [f"  [{page.get('url_path', page.get('url', ''))}] {page.get('title', '')}"]
        if page.get("meta_description"):
            lines.append(f"    Meta: {page['meta_description']}")
        if page.get("body_excerpt"):
            lines.append(f"    Excerpt: {page['body_excerpt'][:300]}")
        return "\n".join(lines)

    nav_pages_block = "\n".join(
        fmt_page(p) for p in scraped_data.get("nav_pages", [])
    ) or "  (none scraped)"

    secondary_block = "\n".join(
        fmt_page(v) for k, v in scraped_data.get("secondary_pages", {}).items() if v
    ) or "  (none found)"

    # Summarise JSON-LD (avoid dumping raw nested objects)
    ld_lines = []
    for obj in scraped_data.get("json_ld", [])[:5]:
        graph = obj.get("@graph", [obj])
        for item in graph:
            ld_type = item.get("@type", "")
            name = item.get("name", "")
            desc = item.get("description", "")
            if ld_type or name:
                ld_lines.append(f"  type={ld_type} name={name} desc={desc[:100]}")
    ld_block = "\n".join(ld_lines) or "  (none)"

    trust_block = "\n".join(
        f"  - {s}" for s in scraped_data.get("trust_signals", [])
    ) or "  (none detected)"

    return f"""Account: {account_name}
Website: {scraped_data.get('base_url', '')}

--- SCRAPED DATA ---

Brand:    {scraped_data.get('brand_name') or '(unknown)'}
Language: {scraped_data.get('language') or '(unknown)'}
Currency: {scraped_data.get('currency') or '(unknown)'}
Tagline:  {scraped_data.get('tagline') or '(none)'}

Trust Signals:
{trust_block}

Navigation Pages:
{nav_pages_block}

Secondary Pages:
{secondary_block}

JSON-LD Summary:
{ld_block}

--- END SCRAPED DATA ---

Generate:
  - 8 to 12 sitelinks
  - 8 to 12 callouts
  - 3 to 5 structured snippets

Use ONLY structured snippet headers that genuinely match this business.
Write ALL text in: {scraped_data.get('language') or 'the website language'}.
Output ONLY valid JSON — no markdown, no explanation.
"""


# ---------------------------------------------------------------------------
# Claude asset generation
# ---------------------------------------------------------------------------

def generate_assets_with_claude(scraped_data: dict, account_name: str) -> dict:
    """
    Call the Anthropic API with prompt caching to generate ad assets.
    Returns {"sitelinks": [...], "callouts": [...], "structured_snippets": [...]}.
    """
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    user_prompt = build_user_prompt(scraped_data, account_name)

    print("\nGenerating assets with Claude...")

    for attempt in range(1, 3):  # retry once on failure
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": user_prompt,
                                "cache_control": {"type": "ephemeral"},
                            }
                        ],
                    }
                ],
            )
            break
        except anthropic.APIError as e:
            if attempt == 2:
                sys.exit(f"ERROR: Claude API failed after 2 attempts — {e}")
            print(f"  Claude API error (attempt {attempt}): {e}. Retrying...", file=sys.stderr)

    raw = response.content[0].text.strip()

    # Strip accidental markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()

    try:
        assets = json.loads(raw)
    except json.JSONDecodeError as e:
        print("ERROR: Claude returned non-JSON response:", file=sys.stderr)
        print(raw[:500], file=sys.stderr)
        sys.exit(f"JSON parse error: {e}")

    # Basic structure validation
    for key in ("sitelinks", "callouts", "structured_snippets"):
        if key not in assets:
            assets[key] = []

    return assets


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
