"""Find the Dorin Sijaj Google Ads account under the MCC."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from google_ads_assets import init_google_ads_client, load_google_ads_config  # noqa: E402


def main():
    client = init_google_ads_client()
    cfg = load_google_ads_config()
    mcc = cfg.get("login_customer_id", "").replace("-", "")
    ga = client.get_service("GoogleAdsService")
    q = """
        SELECT customer_client.id, customer_client.descriptive_name,
               customer_client.currency_code, customer_client.status
        FROM customer_client
        WHERE customer_client.manager = false
    """
    for batch in ga.search_stream(customer_id=mcc, query=q):
        for row in batch.results:
            cc = row.customer_client
            name = (cc.descriptive_name or "").lower()
            if "dorin" in name or "sijaj" in name:
                print(f"  {cc.id}  {cc.descriptive_name}  cur={cc.currency_code}  status={cc.status}")


if __name__ == "__main__":
    main()
