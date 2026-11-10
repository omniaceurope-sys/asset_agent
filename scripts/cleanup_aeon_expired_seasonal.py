"""
Unlink expired Spring/Summer promotion assets still ENABLED at account level
on DE, SK, CZ, SI. Finds any PROMOTION CustomerAsset whose redemption_end_date
is in the past and removes the link. The asset record stays (API cannot
hard-delete), but it stops cluttering the live-promos list.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from google_ads_assets import init_google_ads_client, _parse_partial_failures  # noqa: E402

TODAY = date.today().isoformat()

ACCOUNTS = [
    ("DE", "1995608260"),
    ("SK", "9217995931"),
    ("CZ", "8011554450"),
    ("SI", "3972310409"),
]


def find_expired_promo_links(client, customer_id: str):
    """Return list of (customer_asset_rn, asset_rn, occasion_name, end_date)
    for enabled PROMOTION CustomerAssets whose end_date is in the past."""
    ga = client.get_service("GoogleAdsService")
    q = """
        SELECT
          customer_asset.resource_name,
          customer_asset.status,
          asset.resource_name,
          asset.promotion_asset.occasion,
          asset.promotion_asset.redemption_end_date
        FROM customer_asset
        WHERE customer_asset.field_type = 'PROMOTION'
          AND customer_asset.status = 'ENABLED'
    """
    out = []
    for batch in ga.search_stream(customer_id=customer_id, query=q):
        for row in batch.results:
            end = row.asset.promotion_asset.redemption_end_date
            if end and end < TODAY:
                occ_name = row.asset.promotion_asset.occasion.name \
                    if hasattr(row.asset.promotion_asset.occasion, "name") else "?"
                out.append((
                    row.customer_asset.resource_name,
                    row.asset.resource_name,
                    occ_name,
                    end,
                ))
    return out


def unlink(client, customer_id: str, ca_rns: list[str]):
    if not ca_rns:
        return
    svc = client.get_service("CustomerAssetService")
    ops = []
    for rn in ca_rns:
        op = client.get_type("CustomerAssetOperation")
        op.remove = rn
        ops.append(op)
    req = client.get_type("MutateCustomerAssetsRequest")
    req.customer_id = customer_id
    req.operations.extend(ops)
    req.partial_failure = True
    resp = svc.mutate_customer_assets(request=req)
    failed = _parse_partial_failures(resp, ops)
    for i, _ in enumerate(resp.results):
        status = "FAIL" if i in failed else "OK"
        print(f"    unlink {status}: {ca_rns[i]}")


def main():
    client = init_google_ads_client()
    total = 0
    for market, cid in ACCOUNTS:
        print(f"\n[{market}] {cid}")
        expired = find_expired_promo_links(client, cid)
        if not expired:
            print(f"  nothing expired")
            continue
        for ca_rn, asset_rn, occ, end in expired:
            print(f"  {occ} (ended {end}) — {asset_rn}")
        unlink(client, cid, [x[0] for x in expired])
        total += len(expired)
    print(f"\nTotal links removed: {total}")


if __name__ == "__main__":
    main()
