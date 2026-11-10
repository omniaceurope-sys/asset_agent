"""
Delete the duplicate BLACK_FRIDAY promotion assets just created on UK and US
(from push_aeon_blackfriday_all.py). The original earlier-session promos stay.

To delete an asset safely:
1. Unlink CustomerAsset (so no active link references it)
2. Remove the asset
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from google_ads_assets import init_google_ads_client, _parse_partial_failures  # noqa: E402

# The NEW (duplicate) assets to remove
DUPLICATES = [
    ("4509000147", "customers/4509000147/assets/437992685911"),  # UK
    ("5477580929", "customers/5477580929/assets/437992718284"),  # US
]


def find_customer_asset_links(client, customer_id: str, asset_rn: str) -> list[str]:
    """Return list of CustomerAsset resource_names that link this asset."""
    ga = client.get_service("GoogleAdsService")
    q = f"""
        SELECT customer_asset.resource_name
        FROM customer_asset
        WHERE customer_asset.asset = '{asset_rn}'
    """
    out = []
    for batch in ga.search_stream(customer_id=customer_id, query=q):
        for row in batch.results:
            out.append(row.customer_asset.resource_name)
    return out


def remove_customer_asset_links(client, customer_id: str, ca_rns: list[str]):
    svc = client.get_service("CustomerAssetService")
    ops = []
    for rn in ca_rns:
        op = client.get_type("CustomerAssetOperation")
        op.remove = rn
        ops.append(op)
    if not ops:
        return
    req = client.get_type("MutateCustomerAssetsRequest")
    req.customer_id = customer_id
    req.operations.extend(ops)
    req.partial_failure = True
    resp = svc.mutate_customer_assets(request=req)
    failed = _parse_partial_failures(resp, ops)
    for i, r in enumerate(resp.results):
        status = "FAIL" if i in failed else "OK"
        print(f"    unlink {status}: {ca_rns[i]}")


def main():
    client = init_google_ads_client()
    for cid, asset_rn in DUPLICATES:
        print(f"\n[{cid}] cleaning {asset_rn}")
        links = find_customer_asset_links(client, cid, asset_rn)
        print(f"  found {len(links)} CustomerAsset link(s)")
        remove_customer_asset_links(client, cid, links)
        print(f"  (asset itself stays orphaned in library — API cannot hard-delete)")


if __name__ == "__main__":
    main()
