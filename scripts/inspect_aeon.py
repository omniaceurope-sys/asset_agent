"""
Inspect existing assets on Aeon Athletics UK, US and DE accounts so we can
model new UK/US assets after what already works on DE and avoid duplicates
on UK/US.
"""

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))

from google_ads_assets import init_google_ads_client  # noqa: E402

ACCOUNTS = {
    "4509000147": "Aeon Athletics UK",
    "5477580929": "Aeon Athletics US",
    "1995608260": "Aeon Athletics DE",
}


def fetch_asset_details(client, customer_id: str) -> dict:
    ga_service = client.get_service("GoogleAdsService")
    out = {"sitelinks": [], "callouts": [], "snippets": [], "promotions": [], "images": [], "logos": [], "business_names": []}

    q_sl = """
        SELECT
          asset.sitelink_asset.link_text,
          asset.sitelink_asset.description1,
          asset.sitelink_asset.description2,
          asset.final_urls
        FROM asset
        WHERE asset.type = 'SITELINK'
    """
    q_co = """
        SELECT asset.callout_asset.callout_text
        FROM asset WHERE asset.type = 'CALLOUT'
    """
    q_sn = """
        SELECT asset.structured_snippet_asset.header,
               asset.structured_snippet_asset.values
        FROM asset WHERE asset.type = 'STRUCTURED_SNIPPET'
    """
    q_pr = """
        SELECT
          asset.promotion_asset.promotion_target,
          asset.promotion_asset.discount_modifier,
          asset.promotion_asset.percent_off,
          asset.promotion_asset.money_amount_off.amount_micros,
          asset.promotion_asset.money_amount_off.currency_code,
          asset.promotion_asset.promotion_code,
          asset.promotion_asset.orders_over_amount.amount_micros,
          asset.promotion_asset.orders_over_amount.currency_code,
          asset.promotion_asset.occasion,
          asset.promotion_asset.redemption_start_date,
          asset.promotion_asset.redemption_end_date,
          asset.promotion_asset.language_code,
          asset.final_urls
        FROM asset WHERE asset.type = 'PROMOTION'
    """
    q_logo = """
        SELECT asset.name, asset.image_asset.full_size.url
        FROM asset WHERE asset.type = 'IMAGE'
    """
    q_bn = """
        SELECT asset.name, asset.type
        FROM asset WHERE asset.type = 'BUSINESS_NAME'
    """

    try:
        for batch in ga_service.search_stream(customer_id=customer_id, query=q_sl):
            for row in batch.results:
                sl = row.asset.sitelink_asset
                urls = list(row.asset.final_urls)
                out["sitelinks"].append({
                    "title": sl.link_text,
                    "d1": sl.description1,
                    "d2": sl.description2,
                    "url": urls[0] if urls else "",
                })
    except Exception as e:
        print(f"  WARN sitelinks: {e}")

    try:
        for batch in ga_service.search_stream(customer_id=customer_id, query=q_co):
            for row in batch.results:
                out["callouts"].append(row.asset.callout_asset.callout_text)
    except Exception as e:
        print(f"  WARN callouts: {e}")

    try:
        for batch in ga_service.search_stream(customer_id=customer_id, query=q_sn):
            for row in batch.results:
                sn = row.asset.structured_snippet_asset
                out["snippets"].append({
                    "header": sn.header,
                    "values": list(sn.values),
                })
    except Exception as e:
        print(f"  WARN snippets: {e}")

    try:
        for batch in ga_service.search_stream(customer_id=customer_id, query=q_pr):
            for row in batch.results:
                pr = row.asset.promotion_asset
                out["promotions"].append({
                    "target": pr.promotion_target,
                    "percent_off": pr.percent_off / 1_000_000 if pr.percent_off else None,
                    "money_off": pr.money_amount_off.amount_micros / 1_000_000 if pr.money_amount_off.amount_micros else None,
                    "money_off_currency": pr.money_amount_off.currency_code,
                    "code": pr.promotion_code,
                    "orders_over": pr.orders_over_amount.amount_micros / 1_000_000 if pr.orders_over_amount.amount_micros else None,
                    "orders_over_currency": pr.orders_over_amount.currency_code,
                    "occasion": str(pr.occasion),
                    "start": str(pr.redemption_start_date),
                    "end": str(pr.redemption_end_date),
                    "lang": pr.language_code,
                    "url": list(row.asset.final_urls)[0] if list(row.asset.final_urls) else "",
                })
    except Exception as e:
        print(f"  WARN promotions: {e}")

    try:
        for batch in ga_service.search_stream(customer_id=customer_id, query=q_logo):
            for row in batch.results:
                out["images"].append({
                    "name": row.asset.name,
                    "url": row.asset.image_asset.full_size.url,
                })
    except Exception as e:
        print(f"  WARN images: {e}")

    try:
        for batch in ga_service.search_stream(customer_id=customer_id, query=q_bn):
            for row in batch.results:
                out["business_names"].append(row.asset.name)
    except Exception as e:
        print(f"  WARN business_names: {str(e)[:200]}")

    return out


def main():
    client = init_google_ads_client()
    for cid, name in ACCOUNTS.items():
        print("\n" + "=" * 70)
        print(f"ACCOUNT {cid} — {name}")
        print("=" * 70)
        data = fetch_asset_details(client, cid)

        print(f"\n-- SITELINKS ({len(data['sitelinks'])}) --")
        for s in data["sitelinks"]:
            print(f"  [{s['title']}] {s['d1']} / {s['d2']}  →  {s['url']}")

        print(f"\n-- CALLOUTS ({len(data['callouts'])}) --")
        for c in data["callouts"]:
            print(f"  • {c}")

        print(f"\n-- STRUCTURED SNIPPETS ({len(data['snippets'])}) --")
        for s in data["snippets"]:
            print(f"  {s['header']}: {', '.join(s['values'])}")

        print(f"\n-- PROMOTIONS ({len(data['promotions'])}) --")
        for p in data["promotions"]:
            print(f"  {p}")

        print(f"\n-- IMAGES / LOGOS ({len(data['images'])}) --")
        for im in data["images"][:30]:
            print(f"  [{im['name']}] {im['url']}")

        print(f"\n-- BUSINESS NAMES ({len(data['business_names'])}) --")
        for b in data["business_names"]:
            print(f"  • {b}")


if __name__ == "__main__":
    main()
