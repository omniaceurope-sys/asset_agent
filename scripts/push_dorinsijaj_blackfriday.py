"""
Push 2 sitelinks + 1 Black Friday promotion extension to the Dorin sijaj
Google Ads account (9043256297). Source: https://dorinsijaj.si/blackfriday/

All three assets link to the Black Friday landing page, Slovenian copy,
created and linked at account level.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from google_ads_assets import (  # noqa: E402
    init_google_ads_client,
    _build_sitelink_operation,
    _parse_partial_failures,
)
from push_aeon_uk_us import (  # noqa: E402
    _build_promotion_operation,
    link_at_account_level,
)

CUSTOMER_ID = "9043256297"
ACCOUNT_NAME = "Dorin sijaj"
URL = "https://dorinsijaj.si/blackfriday/"

SITELINKS = [
    {
        "title": "Črni petek do -63 %",
        "description1": "Najvišji popust leta",
        "description2": "Brezplačna dostava nad 50 €",
        "final_url": URL,
    },
    {
        "title": "Seti in čistila v akciji",
        "description1": "Kopalnica, kuhinja, tla, steklo",
        "description2": "Zaloge so omejene",
        "final_url": URL,
    },
]

PROMO = {
    "occasion": "BLACK_FRIDAY",
    "discount_modifier": "UP_TO",
    "percent_off_pct": 63,
    "promotion_target": "Čistila in seti",
    "language_code": "sl",
    "redemption_start": "2026-11-10",
    "redemption_end": "2026-12-02",
    "final_url": URL,
}


def verify_limits():
    errors = []
    for sl in SITELINKS:
        for field, limit in [("title", 25), ("description1", 35), ("description2", 35)]:
            v = sl[field]
            if len(v) > limit:
                errors.append(f"{field} ({len(v)}): {v!r}")
    if len(PROMO["promotion_target"]) > 25:
        errors.append(f"promotion_target ({len(PROMO['promotion_target'])}): {PROMO['promotion_target']!r}")
    if errors:
        print("CHARACTER LIMIT VIOLATIONS:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)


def dump_errors(resp):
    if not resp.partial_failure_error or not resp.partial_failure_error.details:
        return
    from google.ads.googleads.v24.errors.types.errors import GoogleAdsFailure  # noqa: PLC0415
    for detail in resp.partial_failure_error.details:
        failure = GoogleAdsFailure()
        failure_pb = type(failure).pb(failure)
        detail.Unpack(failure_pb)
        failure = type(failure).wrap(failure_pb)
        for err in failure.errors:
            print(f"    err: {err.message}")


def push_mutate(client, operations, label_fn):
    svc = client.get_service("AssetService")
    req = client.get_type("MutateAssetsRequest")
    req.customer_id = CUSTOMER_ID
    req.operations.extend(operations)
    req.partial_failure = True
    resp = svc.mutate_assets(request=req)
    failed = _parse_partial_failures(resp, operations)
    rns = []
    for i, r in enumerate(resp.results):
        if i in failed or not r.resource_name:
            print(f"  ✗ {label_fn(i)} (API rejected)")
            rns.append(None)
        else:
            print(f"  ✓ {label_fn(i)}")
            rns.append(r.resource_name)
    if any(i in failed for i in range(len(operations))):
        dump_errors(resp)
    return rns


def fetch_existing_sitelink_titles(client) -> set[str]:
    ga = client.get_service("GoogleAdsService")
    out: set[str] = set()
    for batch in ga.search_stream(customer_id=CUSTOMER_ID, query=(
        "SELECT asset.sitelink_asset.link_text FROM asset "
        "WHERE asset.type = 'SITELINK'"
    )):
        for row in batch.results:
            txt = row.asset.sitelink_asset.link_text
            if txt:
                out.add(txt.lower())
    return out


def fetch_existing_blackfriday() -> int:
    """Return BLACK_FRIDAY occasion int to compare."""
    # Use the enum numeric value — BLACK_FRIDAY == 11 in PromotionExtensionOccasionEnum
    return 11


def existing_blackfriday_promos(client) -> list[str]:
    ga = client.get_service("GoogleAdsService")
    out = []
    for batch in ga.search_stream(customer_id=CUSTOMER_ID, query=(
        "SELECT asset.resource_name, asset.promotion_asset.occasion FROM asset "
        "WHERE asset.type = 'PROMOTION'"
    )):
        for row in batch.results:
            if int(row.asset.promotion_asset.occasion) == 11:
                out.append(row.asset.resource_name)
    return out


def main():
    verify_limits()
    client = init_google_ads_client()
    print(f"\nAccount: {CUSTOMER_ID} ({ACCOUNT_NAME})")

    # --- SITELINKS ---
    existing_titles = fetch_existing_sitelink_titles(client)
    to_push = [sl for sl in SITELINKS if sl["title"].lower() not in existing_titles]
    skipped = [sl for sl in SITELINKS if sl["title"].lower() in existing_titles]
    for sl in skipped:
        print(f"  ⊘ sitelink '{sl['title']}' already exists")

    print("\nCreating sitelinks...")
    sl_rns = []
    if to_push:
        ops = [_build_sitelink_operation(client, sl) for sl in to_push]
        sl_rns = push_mutate(
            client, ops,
            lambda i: f"{to_push[i]['title']} -> {to_push[i]['final_url']}"
        )

    print("\nLinking sitelinks at account level...")
    sl_linked, sl_link_failed = (0, 0)
    if sl_rns:
        sl_linked, sl_link_failed = link_at_account_level(
            client, CUSTOMER_ID, sl_rns, "SITELINK",
            lambda i: to_push[i]["title"]
        )

    # --- PROMOTION ---
    print("\nCreating Black Friday promotion...")
    existing_bf = existing_blackfriday_promos(client)
    if existing_bf:
        print(f"  ⊘ BLACK_FRIDAY promo already exists: {existing_bf}")
        pr_rns = []
    else:
        pr_op = _build_promotion_operation(client, PROMO)
        pr_rns = push_mutate(
            client, [pr_op],
            lambda i: f"BLACK_FRIDAY up-to-{PROMO['percent_off_pct']}% -> {PROMO['final_url']}"
        )

    print("\nLinking promotion at account level...")
    pr_linked, pr_link_failed = (0, 0)
    if pr_rns:
        pr_linked, pr_link_failed = link_at_account_level(
            client, CUSTOMER_ID, pr_rns, "PROMOTION",
            lambda i: f"BLACK_FRIDAY up-to-{PROMO['percent_off_pct']}%"
        )

    # --- SUMMARY ---
    sl_created = sum(1 for r in sl_rns if r)
    pr_created = sum(1 for r in pr_rns if r)
    print("\n" + "=" * 60)
    print(f"SUMMARY  —  {CUSTOMER_ID} ({ACCOUNT_NAME})")
    print(f"  Sitelinks:  {sl_created} created, {len(skipped)} skipped, linked: {sl_linked}")
    print(f"  Promotion:  {pr_created} created, "
          f"{1 if existing_bf else 0} skipped, linked: {pr_linked}")
    print("=" * 60)


if __name__ == "__main__":
    main()
