"""
Push Aeon Athletics assets to UK (450-900-0147) and US (547-758-0929).

Both accounts share the same Shopify storefront (aeonathletics.com).
Currency is forced per market via ?country=GB / ?country=US — verified in
Shopify Markets to switch pricing to GBP / USD respectively.

Creates account-level sitelinks, callouts, structured snippets, a Black
Friday promotion asset, and copies the Aeon logo image across from the DE
account (1995608260).

Usage:
    python scripts/push_aeon_uk_us.py --market uk
    python scripts/push_aeon_uk_us.py --market us
    python scripts/push_aeon_uk_us.py --market both
"""

import argparse
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent))

import requests  # noqa: E402

from google_ads_assets import (  # noqa: E402
    init_google_ads_client,
    fetch_existing_assets,
    _build_sitelink_operation,
    _build_callout_operation,
    _build_snippet_operation,
    _parse_partial_failures,
)

# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

AEON_DE = "1995608260"          # source for the logo image

MARKETS = {
    "uk": {
        "customer_id": "4509000147",
        "name": "Aeon Athletics UK",
        "country_qs": "?country=GB",
        "language": "en",
    },
    "us": {
        "customer_id": "5477580929",
        "name": "Aeon Athletics US",
        "country_qs": "?country=US",
        "language": "en",
    },
}

BASE = "https://aeonathletics.com"


# ---------------------------------------------------------------------------
# Asset content — tailored per market (UK English vs US English)
# ---------------------------------------------------------------------------

def build_content(market: str) -> dict:
    qs = MARKETS[market]["country_qs"]

    def u(path: str) -> str:
        return f"{BASE}{path}{qs}"

    # UK uses "Cosy", "Trainers"; US uses "Cozy", "Sneakers". No sneakers here
    # but we do have cosy → cozy, and we vary the shipping copy per market.
    cosy = "Cosy" if market == "uk" else "Cozy"

    sitelinks = [
        {
            "title": "Leggings",
            "description1": "Push-Up & Shaping Leggings",
            "description2": "120,000+ Happy Women",
            "final_url": u("/collections/leggings"),
        },
        {
            "title": "Shorts",
            "description1": "Seamless Shorts for Gym & Sport",
            "description2": "Comfy & Figure-Flattering Fit",
            "final_url": u("/collections/shorts"),
        },
        {
            "title": "Sports Bras & Tops",
            "description1": "Seamless Bras With Full Support",
            "description2": "Stylish for Gym & Everyday",
            "final_url": u("/collections/bras-tops"),
        },
        {
            "title": "Joggers",
            "description1": "Premium Joggers for Every Day",
            "description2": "Comfort Meets Style",
            "final_url": u("/collections/joggers"),
        },
        {
            "title": "Hoodies",
            "description1": f"{cosy} Hoodies for Gym & Lounge",
            "description2": "Premium Soft Materials",
            "final_url": u("/collections/hoodies"),
        },
        {
            "title": "T-Shirts & Jackets",
            "description1": "Tops, Tees & Light Jackets",
            "description2": "Breathable & Soft Fabrics",
            "final_url": u("/collections/t-shirts-tops"),
        },
        {
            "title": "Skorts & Dresses",
            "description1": "Sporty-Elegant Skorts",
            "description2": "Perfect for Tennis & Yoga",
            "final_url": u("/collections/skorts-dresses"),
        },
        {
            "title": "Jumpsuits",
            "description1": "All-in-One Sport Jumpsuits",
            "description2": "Figure-Hugging & Comfortable",
            "final_url": u("/collections/jumpsuits"),
        },
        {
            "title": "Push-Up Leggings",
            "description1": "The Original Booty Lift",
            "description2": "Trusted by 120,000+ Women",
            "final_url": u("/pages/push-up-leggings-hero"),
        },
        {
            "title": "Men's Collection",
            "description1": "Premium Sportswear for Men",
            "description2": "Joggers, Tees, Tracksuits",
            "final_url": u("/collections/mens"),
        },
        {
            "title": "Women's Collection",
            "description1": "Full Activewear Range",
            "description2": "Leggings, Bras, Hoodies & More",
            "final_url": u("/collections/womens"),
        },
        {
            "title": "Sale - Up to 80% Off",
            "description1": "Biggest Sale of the Season",
            "description2": "For a Limited Time Only",
            "final_url": u("/collections/sale"),
        },
    ]

    # UK vs US: shipping phrasing differs (UK Shipping / US Shipping)
    ship = "Free UK Shipping" if market == "uk" else "Free US Shipping"

    callouts = [
        "Push-Up Booty-Lift",
        "Seamless Sportswear",
        "120,000+ Happy Women",
        "30-Day Returns",
        "Women's & Men's Wear",
        "Save With Bundles & Sets",
        "5-Star Reviews",
        "For Gym, Yoga & Running",
        "Premium Sportswear",
        "Stylish & Functional",
        ship,
        "Secure Checkout",
    ]

    structured_snippets = [
        {
            "header": "Types",
            "values": [
                "Leggings", "Shorts", "Sports Bras", "Hoodies",
                "Joggers", "T-Shirts", "Jumpsuits", "Accessories",
            ],
        },
        {
            "header": "Styles",
            "values": [
                "Motion", "FlexMotion", "Empower", "Signature",
                "Second Skin", "TechPRO", "Elevate", "Essentials",
            ],
        },
    ]

    # Black Friday promotion extension
    # Google's PromotionTarget string is 1–25 chars, up to Sitelink standard.
    promotion = {
        "occasion": "BLACK_FRIDAY",
        "discount_modifier": "UP_TO",
        "percent_off_pct": 80,                 # UP TO 80% OFF
        "promotion_target": "Everything",      # what it applies to
        "language_code": "en",
        "redemption_start": "2026-11-10",
        "redemption_end": "2026-12-02",
        "final_url": u("/collections/sale"),
    }

    return {
        "sitelinks": sitelinks,
        "callouts": callouts,
        "structured_snippets": structured_snippets,
        "promotion": promotion,
    }


# ---------------------------------------------------------------------------
# Character-limit verifier (fail-fast before touching the API)
# ---------------------------------------------------------------------------

def verify_limits(content: dict) -> None:
    errors = []
    for sl in content["sitelinks"]:
        for field, limit in [("title", 25), ("description1", 35), ("description2", 35)]:
            v = sl.get(field, "")
            if len(v) > limit:
                errors.append(f"sitelink {field!r} ({len(v)} chars): {v!r}")
    for co in content["callouts"]:
        if len(co) > 25:
            errors.append(f"callout ({len(co)} chars): {co!r}")
    for sn in content["structured_snippets"]:
        for v in sn["values"]:
            if len(v) > 25:
                errors.append(f"snippet value ({len(v)} chars): {v!r}")
    if errors:
        print("CHARACTER LIMIT VIOLATIONS:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Push + link helpers (same pattern as push_heroclothing_cz.py)
# ---------------------------------------------------------------------------

def push_assets_and_collect_rns(client, customer_id, operations, label_fn):
    asset_service = client.get_service("AssetService")
    try:
        request = client.get_type("MutateAssetsRequest")
        request.customer_id = customer_id
        request.operations.extend(operations)
        request.partial_failure = True
        response = asset_service.mutate_assets(request=request)
    except Exception as e:
        print(f"  ✗ Batch failed entirely — {e}")
        return [None] * len(operations)

    failed_idx = _parse_partial_failures(response, operations)
    resource_names = []
    for i, result in enumerate(response.results):
        if i in failed_idx or not result.resource_name:
            print(f"  ✗ {label_fn(i)} (API rejected)")
            resource_names.append(None)
        else:
            print(f"  ✓ {label_fn(i)}")
            resource_names.append(result.resource_name)
    return resource_names


def link_at_account_level(client, customer_id, resource_names, field_type_str, label_fn):
    customer_asset_service = client.get_service("CustomerAssetService")
    field_type_enum = client.enums.AssetFieldTypeEnum
    field_type = getattr(field_type_enum, field_type_str)

    operations = []
    op_index_to_orig_index = []
    for i, rn in enumerate(resource_names):
        if rn is None:
            continue
        op = client.get_type("CustomerAssetOperation")
        ca = op.create
        ca.asset = rn
        ca.field_type = field_type
        operations.append(op)
        op_index_to_orig_index.append(i)

    if not operations:
        return 0, 0

    try:
        request = client.get_type("MutateCustomerAssetsRequest")
        request.customer_id = customer_id
        request.operations.extend(operations)
        request.partial_failure = True
        response = customer_asset_service.mutate_customer_assets(request=request)
    except Exception as e:
        print(f"  ✗ Account-level link batch failed — {e}")
        return 0, len(operations)

    failed_idx = _parse_partial_failures(response, operations)
    linked = 0
    failed = 0
    for j, _result in enumerate(response.results):
        orig_i = op_index_to_orig_index[j]
        if j in failed_idx:
            print(f"  ✗ link {label_fn(orig_i)}")
            failed += 1
        else:
            print(f"  ✓ link {label_fn(orig_i)}")
            linked += 1
    return linked, failed


# ---------------------------------------------------------------------------
# Promotion asset builder
# ---------------------------------------------------------------------------

def _build_promotion_operation(client, promo: dict):
    """
    Build a Black Friday promotion asset.

    Google Ads promotion asset fields:
      occasion                  — PromotionExtensionOccasionEnum string
      discount_modifier         — PromotionExtensionDiscountModifierEnum (UP_TO / UNSPECIFIED)
      percent_off               — int, micros (e.g. 80_000_000 = 80%)
      promotion_target          — short string (what the promo applies to)
      language_code             — ISO 639-1 (en)
      redemption_start_date     — 'YYYY-MM-DD'
      redemption_end_date       — 'YYYY-MM-DD'
      final_urls                — landing page
    """
    op = client.get_type("AssetOperation")
    asset = op.create
    pa = asset.promotion_asset

    pa.occasion = getattr(client.enums.PromotionExtensionOccasionEnum, promo["occasion"])
    pa.discount_modifier = getattr(
        client.enums.PromotionExtensionDiscountModifierEnum, promo["discount_modifier"]
    )
    # Google Ads convention: 1,000,000 micros == 100%. So 80% == 800,000.
    pa.percent_off = int(promo["percent_off_pct"] * 10_000)
    pa.promotion_target = promo["promotion_target"]
    pa.language_code = promo["language_code"]
    pa.redemption_start_date = promo["redemption_start"]
    pa.redemption_end_date = promo["redemption_end"]
    asset.final_urls.append(promo["final_url"])
    return op


def fetch_existing_promotions(client, customer_id: str) -> set:
    """Return set of occasion strings for existing PROMOTION assets."""
    ga_service = client.get_service("GoogleAdsService")
    query = """
        SELECT asset.promotion_asset.occasion
        FROM asset WHERE asset.type = 'PROMOTION'
    """
    out = set()
    try:
        for batch in ga_service.search_stream(customer_id=customer_id, query=query):
            for row in batch.results:
                out.add(str(row.asset.promotion_asset.occasion))
    except Exception as e:
        print(f"  WARN existing promotions: {str(e)[:200]}")
    return out


# ---------------------------------------------------------------------------
# Logo image — copy the Aeon logo from DE to the target account
# ---------------------------------------------------------------------------

AEON_LOGO_URL = "https://tpc.googlesyndication.com/simgad/892564183489571702"
AEON_LOGO_NAME = "Aeon_black.png"


def download_logo_bytes() -> bytes | None:
    try:
        r = requests.get(AEON_LOGO_URL, timeout=15)
        r.raise_for_status()
        return r.content
    except Exception as e:
        print(f"  ✗ Could not download logo from {AEON_LOGO_URL}: {e}")
        return None


def fetch_existing_image_names(client, customer_id: str) -> set:
    ga_service = client.get_service("GoogleAdsService")
    query = """
        SELECT asset.name FROM asset WHERE asset.type = 'IMAGE'
    """
    out = set()
    try:
        for batch in ga_service.search_stream(customer_id=customer_id, query=query):
            for row in batch.results:
                if row.asset.name:
                    out.add(row.asset.name.lower())
    except Exception as e:
        print(f"  WARN existing images: {str(e)[:200]}")
    return out


def upload_logo(client, customer_id: str, image_bytes: bytes):
    """Upload the Aeon logo image asset. Returns resource_name or None."""
    op = client.get_type("AssetOperation")
    asset = op.create
    asset.name = AEON_LOGO_NAME
    asset.type_ = client.enums.AssetTypeEnum.IMAGE
    asset.image_asset.data = image_bytes

    asset_service = client.get_service("AssetService")
    try:
        request = client.get_type("MutateAssetsRequest")
        request.customer_id = customer_id
        request.operations.extend([op])
        request.partial_failure = True
        response = asset_service.mutate_assets(request=request)
    except Exception as e:
        print(f"  ✗ Logo upload failed entirely: {e}")
        return None
    failed_idx = _parse_partial_failures(response, [op])
    if 0 in failed_idx or not response.results[0].resource_name:
        print(f"  ✗ Logo upload rejected by API")
        return None
    return response.results[0].resource_name


# ---------------------------------------------------------------------------
# Per-market runner
# ---------------------------------------------------------------------------

def run_market(client, market: str, logo_bytes: bytes | None):
    cfg = MARKETS[market]
    customer_id = cfg["customer_id"]
    account_name = cfg["name"]

    content = build_content(market)
    verify_limits(content)

    print(f"\n{'=' * 70}")
    print(f"ACCOUNT {customer_id} — {account_name}")
    print(f"{'=' * 70}")

    existing = fetch_existing_assets(client, customer_id)
    existing_promos = fetch_existing_promotions(client, customer_id)
    existing_images = fetch_existing_image_names(client, customer_id)

    # --- SITELINKS ---
    print("\nCreating sitelinks...")
    sl_to_push = []
    sl_skipped = []
    for sl in content["sitelinks"]:
        if sl["title"].lower() in existing["sitelink_titles"]:
            print(f"  ⊘ {sl['title']} (already exists)")
            sl_skipped.append(sl["title"])
        else:
            sl_to_push.append(sl)
    sl_ops = [_build_sitelink_operation(client, sl) for sl in sl_to_push]
    sl_rns = push_assets_and_collect_rns(
        client, customer_id, sl_ops,
        lambda i: f"{sl_to_push[i]['title']} -> {sl_to_push[i]['final_url']}"
    ) if sl_ops else []

    print("\nLinking sitelinks at account level...")
    sl_linked, sl_link_failed = link_at_account_level(
        client, customer_id, sl_rns, "SITELINK",
        lambda i: sl_to_push[i]["title"]
    ) if sl_rns else (0, 0)

    # --- CALLOUTS ---
    print("\nCreating callouts...")
    co_to_push = []
    co_skipped = []
    for text in content["callouts"]:
        if text.lower() in existing["callout_texts"]:
            print(f"  ⊘ {text} (already exists)")
            co_skipped.append(text)
        else:
            co_to_push.append(text)
    co_ops = [_build_callout_operation(client, t) for t in co_to_push]
    co_rns = push_assets_and_collect_rns(
        client, customer_id, co_ops,
        lambda i: co_to_push[i]
    ) if co_ops else []

    print("\nLinking callouts at account level...")
    co_linked, co_link_failed = link_at_account_level(
        client, customer_id, co_rns, "CALLOUT",
        lambda i: co_to_push[i]
    ) if co_rns else (0, 0)

    # --- STRUCTURED SNIPPETS ---
    print("\nCreating structured snippets...")
    sn_to_push = []
    sn_skipped = []
    for snippet in content["structured_snippets"]:
        if snippet["header"].lower() in existing["snippet_headers"]:
            print(f"  ⊘ {snippet['header']} (already exists)")
            sn_skipped.append(snippet["header"])
        else:
            sn_to_push.append(snippet)
    sn_ops = [_build_snippet_operation(client, s) for s in sn_to_push]
    sn_rns = push_assets_and_collect_rns(
        client, customer_id, sn_ops,
        lambda i: f"{sn_to_push[i]['header']}: {', '.join(sn_to_push[i]['values'])}"
    ) if sn_ops else []

    print("\nLinking structured snippets at account level...")
    sn_linked, sn_link_failed = link_at_account_level(
        client, customer_id, sn_rns, "STRUCTURED_SNIPPET",
        lambda i: sn_to_push[i]["header"]
    ) if sn_rns else (0, 0)

    # --- PROMOTION ---
    print("\nCreating promotion asset (Black Friday)...")
    promo = content["promotion"]
    pr_rns = []
    pr_skipped = []
    if promo["occasion"] in existing_promos:
        print(f"  ⊘ {promo['occasion']} promotion already exists")
        pr_skipped.append(promo["occasion"])
    else:
        pr_op = _build_promotion_operation(client, promo)
        pr_rns = push_assets_and_collect_rns(
            client, customer_id, [pr_op],
            lambda i: f"BLACK_FRIDAY up-to-{promo['percent_off_pct']}% -> {promo['final_url']}"
        )

    print("\nLinking promotion at account level...")
    pr_linked, pr_link_failed = link_at_account_level(
        client, customer_id, pr_rns, "PROMOTION",
        lambda i: f"BLACK_FRIDAY up-to-{promo['percent_off_pct']}%"
    ) if pr_rns else (0, 0)

    # --- LOGO IMAGE ---
    print("\nUploading Aeon logo image...")
    lg_rns = []
    if AEON_LOGO_NAME.lower() in existing_images:
        print(f"  ⊘ {AEON_LOGO_NAME} already exists")
    elif logo_bytes is None:
        print(f"  ✗ Logo bytes not available — skipping")
    else:
        rn = upload_logo(client, customer_id, logo_bytes)
        if rn:
            print(f"  ✓ Uploaded {AEON_LOGO_NAME}")
            lg_rns = [rn]
        else:
            print(f"  ✗ Upload failed")

    print("\nLinking logo at account level...")
    lg_linked, lg_link_failed = link_at_account_level(
        client, customer_id, lg_rns, "LOGO",
        lambda i: AEON_LOGO_NAME
    ) if lg_rns else (0, 0)

    # --- SUMMARY ---
    sl_created = sum(1 for r in sl_rns if r)
    co_created = sum(1 for r in co_rns if r)
    sn_created = sum(1 for r in sn_rns if r)
    pr_created = sum(1 for r in pr_rns if r)

    print("\n" + "-" * 60)
    print(f"RESULT  —  {customer_id} ({account_name})")
    print(f"  Sitelinks:  {sl_created} created, {len(sl_skipped)} skipped, linked: {sl_linked}")
    print(f"  Callouts:   {co_created} created, {len(co_skipped)} skipped, linked: {co_linked}")
    print(f"  Snippets:   {sn_created} created, {len(sn_skipped)} skipped, linked: {sn_linked}")
    print(f"  Promotion:  {pr_created} created, {len(pr_skipped)} skipped, linked: {pr_linked}")
    print(f"  Logo:       {len(lg_rns)} uploaded, linked: {lg_linked}")
    print("-" * 60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", choices=["uk", "us", "both"], default="both")
    args = parser.parse_args()

    client = init_google_ads_client()

    # Download logo once, reuse across markets
    print("\nDownloading Aeon logo from DE source...")
    logo_bytes = download_logo_bytes()
    if logo_bytes:
        print(f"  ✓ Got {len(logo_bytes)} bytes")

    targets = ["uk", "us"] if args.market == "both" else [args.market]
    for m in targets:
        run_market(client, m, logo_bytes)


if __name__ == "__main__":
    main()
