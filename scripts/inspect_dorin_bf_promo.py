"""Inspect existing BLACK_FRIDAY promo on Dorin sijaj (and whether linked)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from google_ads_assets import init_google_ads_client  # noqa: E402

CID = "9043256297"


def main():
    client = init_google_ads_client()
    ga = client.get_service("GoogleAdsService")

    # Promo asset detail
    q1 = """
        SELECT
          asset.resource_name,
          asset.promotion_asset.occasion,
          asset.promotion_asset.discount_modifier,
          asset.promotion_asset.percent_off,
          asset.promotion_asset.money_amount_off.amount_micros,
          asset.promotion_asset.money_amount_off.currency_code,
          asset.promotion_asset.promotion_code,
          asset.promotion_asset.orders_over_amount.amount_micros,
          asset.promotion_asset.redemption_start_date,
          asset.promotion_asset.redemption_end_date,
          asset.promotion_asset.language_code,
          asset.promotion_asset.promotion_target,
          asset.final_urls
        FROM asset
        WHERE asset.type = 'PROMOTION'
    """
    print("All PROMOTION assets on Dorin sijaj:")
    promo_rns = []
    for batch in ga.search_stream(customer_id=CID, query=q1):
        for row in batch.results:
            pa = row.asset.promotion_asset
            occ_int = int(pa.occasion)
            occ_name = pa.occasion.name if hasattr(pa.occasion, "name") else str(occ_int)
            urls = list(row.asset.final_urls)
            pct = pa.percent_off / 10_000 if pa.percent_off else None
            mod = pa.discount_modifier.name if hasattr(pa.discount_modifier, "name") else str(pa.discount_modifier)
            print(f"  asset={row.asset.resource_name.split('/')[-1]}  "
                  f"occ={occ_name}({occ_int})  mod={mod}  pct={pct}  "
                  f"start={pa.redemption_start_date}  end={pa.redemption_end_date}  "
                  f"lang={pa.language_code}  target={pa.promotion_target!r}")
            print(f"       url={urls[0] if urls else ''}")
            promo_rns.append(row.asset.resource_name)

    # Links
    print("\nAccount-level PROMOTION links (CustomerAsset):")
    q2 = """
        SELECT
          customer_asset.resource_name,
          customer_asset.status,
          asset.resource_name,
          asset.promotion_asset.occasion
        FROM customer_asset
        WHERE customer_asset.field_type = 'PROMOTION'
    """
    for batch in ga.search_stream(customer_id=CID, query=q2):
        for row in batch.results:
            occ_int = int(row.asset.promotion_asset.occasion)
            occ_name = row.asset.promotion_asset.occasion.name \
                if hasattr(row.asset.promotion_asset.occasion, "name") else str(occ_int)
            status_name = str(row.customer_asset.status).split(".")[-1]
            print(f"  [{status_name}]  asset={row.asset.resource_name.split('/')[-1]}  "
                  f"occ={occ_name}({occ_int})  ca={row.customer_asset.resource_name}")


if __name__ == "__main__":
    main()
