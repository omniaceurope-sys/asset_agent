"""
List all Aeon Athletics child accounts under the MCC and, for each, print
the domains observed on existing sitelink final URLs — so we can pick the
right local domain + /collections/sale path per market.
"""
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))

from google_ads_assets import init_google_ads_client, load_google_ads_config  # noqa: E402


def list_aeon_accounts(client, mcc_id: str) -> list[dict]:
    ga = client.get_service("GoogleAdsService")
    query = """
        SELECT
          customer_client.id,
          customer_client.descriptive_name,
          customer_client.currency_code,
          customer_client.time_zone,
          customer_client.status,
          customer_client.manager
        FROM customer_client
        WHERE customer_client.manager = false
    """
    out = []
    for batch in ga.search_stream(customer_id=mcc_id, query=query):
        for row in batch.results:
            cc = row.customer_client
            name = cc.descriptive_name or ""
            if "aeon" in name.lower():
                out.append({
                    "id": str(cc.id),
                    "name": name,
                    "currency": cc.currency_code,
                    "tz": cc.time_zone,
                    "status": str(cc.status),
                })
    return sorted(out, key=lambda x: x["name"].lower())


def domains_from_sitelinks(client, customer_id: str) -> dict[str, int]:
    """Count unique domains across existing sitelink final URLs."""
    ga = client.get_service("GoogleAdsService")
    q = """
        SELECT asset.final_urls FROM asset WHERE asset.type = 'SITELINK'
    """
    counts: dict[str, int] = {}
    try:
        for batch in ga.search_stream(customer_id=customer_id, query=q):
            for row in batch.results:
                for u in row.asset.final_urls:
                    host = urlparse(u).netloc.lower()
                    if host:
                        counts[host] = counts.get(host, 0) + 1
    except Exception as e:
        print(f"  WARN sitelinks: {str(e)[:120]}")
    return counts


def main():
    client = init_google_ads_client()
    cfg = load_google_ads_config()
    mcc = cfg.get("login_customer_id", "").replace("-", "")
    print(f"MCC: {mcc}\n")

    accounts = list_aeon_accounts(client, mcc)
    print(f"Found {len(accounts)} Aeon accounts under MCC {mcc}:\n")
    for a in accounts:
        print(f"  {a['id']}  {a['name']:30s}  cur={a['currency']}  tz={a['tz']}  status={a['status']}")

    print("\nDomains on existing sitelinks per account:")
    for a in accounts:
        if a["status"] != "CustomerStatusEnum.CustomerStatus.ENABLED" and a["status"] != "2":
            # Still check — we care about current URLs
            pass
        doms = domains_from_sitelinks(client, a["id"])
        if doms:
            top = sorted(doms.items(), key=lambda x: -x[1])
            print(f"  {a['id']} {a['name']:30s}: {', '.join(f'{d} ({n})' for d, n in top)}")
        else:
            print(f"  {a['id']} {a['name']:30s}: (no sitelinks)")


if __name__ == "__main__":
    main()
