"""
Push 1 sitelink + 1 Black Friday promotion extension to the Acron
(ACRON TRGOVSKO PODJETJE d.o.o.) Google Ads account, 2105147221.
Source: bagsandmore.si/product-category/akcija/crni-petek/
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

CUSTOMER_ID = "2105147221"
ACCOUNT_NAME = "Acron (bagsandmore.si)"
URL = "https://bagsandmore.si/product-category/akcija/crni-petek/"

SITELINK = {
    "title": "Črni petek do -60 %",
    "description1": "Dodatnih -15 % ali -25 %",
    "description2": "Torbice, nahrbtniki, kovčki",
    "final_url": URL,
}

PROMO = {
    "occasion": "BLACK_FRIDAY",
    "discount_modifier": "UP_TO",
    "percent_off_pct": 60,
    "promotion_target": "širok asortiman",
    "language_code": "sl",
    "redemption_start": "2026-11-10",
    "redemption_end": "2026-12-02",
    "final_url": URL,
}


def verify_limits():
    errors = []
    for field, limit in [("title", 25), ("description1", 35), ("description2", 35)]:
        v = SITELINK[field]
        if len(v) > limit:
            errors.append(f"sitelink {field} ({len(v)}): {v!r}")
    if len(PROMO["promotion_target"]) > 25:
        errors.append(f"promotion_target ({len(PROMO['promotion_target'])}): {PROMO['promotion_target']!r}")
    if errors:
        print("CHARACTER LIMIT VIOLATIONS:")
        for e in errors:
            print(f"  X {e}")
        sys.exit(1)


def dump(resp):
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


def push(client, operations, label_fn):
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
            print(f"  X {label_fn(i)} (API rejected)")
            rns.append(None)
        else:
            print(f"  OK {label_fn(i)}")
            rns.append(r.resource_name)
    if any(i in failed for i in range(len(operations))):
        dump(resp)
    return rns


def existing_sitelink_titles(client) -> set[str]:
    ga = client.get_service("GoogleAdsService")
    out: set[str] = set()
    for batch in ga.search_stream(customer_id=CUSTOMER_ID, query=(
        "SELECT asset.sitelink_asset.link_text FROM asset "
        "WHERE asset.type = 'SITELINK'"
    )):
        for row in batch.results:
            t = row.asset.sitelink_asset.link_text
            if t:
                out.add(t.lower())
    return out


def existing_blackfriday_linked(client) -> list[str]:
    """Return resource_names of BLACK_FRIDAY PROMOTION assets currently
    linked and ENABLED at account level."""
    ga = client.get_service("GoogleAdsService")
    out = []
    for batch in ga.search_stream(customer_id=CUSTOMER_ID, query=(
        "SELECT asset.resource_name, asset.promotion_asset.occasion "
        "FROM customer_asset "
        "WHERE customer_asset.field_type = 'PROMOTION' "
        "AND customer_asset.status = 'ENABLED'"
    )):
        for row in batch.results:
            if int(row.asset.promotion_asset.occasion) == 11:  # BLACK_FRIDAY
                out.append(row.asset.resource_name)
    return out


def main():
    verify_limits()
    client = init_google_ads_client()
    print(f"\nAccount: {CUSTOMER_ID} ({ACCOUNT_NAME})")

    # --- SITELINK ---
    existing_titles = existing_sitelink_titles(client)
    if SITELINK["title"].lower() in existing_titles:
        print(f"\n  skip sitelink '{SITELINK['title']}' already exists")
        sl_rns = []
    else:
        print("\nCreating sitelink...")
        sl_ops = [_build_sitelink_operation(client, SITELINK)]
        sl_rns = push(client, sl_ops, lambda i: f"{SITELINK['title']} -> {SITELINK['final_url']}")

        if sl_rns and sl_rns[0]:
            print("Linking sitelink at account level...")
            link_at_account_level(
                client, CUSTOMER_ID, sl_rns, "SITELINK",
                lambda i: SITELINK["title"]
            )

    # --- PROMOTION ---
    linked_bf = existing_blackfriday_linked(client)
    if linked_bf:
        print(f"\n  skip BLACK_FRIDAY promo already linked at account level: {linked_bf}")
        pr_rns = []
    else:
        print("\nCreating Black Friday promotion...")
        pr_op = _build_promotion_operation(client, PROMO)
        pr_rns = push(client, [pr_op], lambda i: f"BLACK_FRIDAY up-to-{PROMO['percent_off_pct']}% -> {PROMO['final_url']}")

        if pr_rns and pr_rns[0]:
            print("Linking promotion at account level...")
            link_at_account_level(
                client, CUSTOMER_ID, pr_rns, "PROMOTION",
                lambda i: f"BLACK_FRIDAY up-to-{PROMO['percent_off_pct']}%"
            )

    # --- SUMMARY ---
    sl_created = sum(1 for r in sl_rns if r)
    pr_created = sum(1 for r in pr_rns if r)
    print("\n" + "=" * 60)
    print(f"SUMMARY  —  {CUSTOMER_ID} ({ACCOUNT_NAME})")
    print(f"  Sitelink:   {sl_created} created and linked")
    print(f"  Promotion:  {pr_created} created and linked")
    print("=" * 60)


if __name__ == "__main__":
    main()
