"""
Verify each of the 6 Aeon accounts has exactly ONE live Black Friday
promotion asset LINKED at account level (CustomerAsset).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from google_ads_assets import init_google_ads_client  # noqa: E402

ACCOUNTS = [
    ("UK", "4509000147"),
    ("US", "5477580929"),
    ("DE", "1995608260"),
    ("SK", "9217995931"),
    ("CZ", "8011554450"),
    ("SI", "3972310409"),
]


def main():
    client = init_google_ads_client()
    ga = client.get_service("GoogleAdsService")

    for market, cid in ACCOUNTS:
        q = """
            SELECT
              customer_asset.resource_name,
              customer_asset.status,
              asset.resource_name,
              asset.promotion_asset.occasion,
              asset.promotion_asset.percent_off,
              asset.promotion_asset.redemption_end_date,
              asset.promotion_asset.language_code,
              asset.promotion_asset.promotion_target,
              asset.final_urls
            FROM customer_asset
            WHERE customer_asset.field_type = 'PROMOTION'
        """
        rows = []
        for batch in ga.search_stream(customer_id=cid, query=q):
            for row in batch.results:
                occ_int = int(row.asset.promotion_asset.occasion)
                occ_name = row.asset.promotion_asset.occasion.name \
                    if hasattr(row.asset.promotion_asset.occasion, "name") else str(occ_int)
                status_name = str(row.customer_asset.status).split(".")[-1]
                rows.append({
                    "ca": row.customer_asset.resource_name,
                    "asset": row.asset.resource_name,
                    "occ": occ_name,
                    "occ_int": occ_int,
                    "pct": row.asset.promotion_asset.percent_off / 10_000,
                    "end": row.asset.promotion_asset.redemption_end_date,
                    "lang": row.asset.promotion_asset.language_code,
                    "target": row.asset.promotion_asset.promotion_target,
                    "url": list(row.asset.final_urls)[0] if list(row.asset.final_urls) else "",
                    "status": status_name,
                })
        print(f"\n[{market}] {cid} — {len(rows)} PROMOTION link(s) total")
        for r in rows:
            print(f"  [{r['status']}]  asset {r['asset'].split('/')[-1]}  "
                  f"occ={r['occ']}({r['occ_int']})  {r['pct']:.0f}%  lang={r['lang']}  "
                  f"target={r['target']!r}  ends {r['end']}")
            print(f"       url={r['url']}")


if __name__ == "__main__":
    main()
