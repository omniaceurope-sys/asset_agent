"""
Push Black Friday promotion assets to all 4 remaining Aeon accounts.
UK and US already have them from earlier this session — the existing-promo
check will skip them if re-run.

Per-market localization:
  DE: aeonathletics.de, lang=de, target='Alles'
  SK: aeonathletics.sk, lang=sk, target='Všetko'
  CZ: aeonathletics.cz, lang=cs, target='Vše'
  SI: aeonathletics.si, lang=sl, target='Vse'
  UK: aeonathletics.com?country=GB, lang=en, target='Everything'
  US: aeonathletics.com?country=US, lang=en, target='Everything'
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from google_ads_assets import init_google_ads_client, _parse_partial_failures  # noqa: E402
from push_aeon_uk_us import (  # noqa: E402
    _build_promotion_operation,
    link_at_account_level,
    fetch_existing_promotions,
)

MARKETS = {
    "UK": {
        "customer_id": "4509000147",
        "final_url": "https://aeonathletics.com/collections/sale?country=GB",
        "language_code": "en",
        "promotion_target": "Everything",
    },
    "US": {
        "customer_id": "5477580929",
        "final_url": "https://aeonathletics.com/collections/sale?country=US",
        "language_code": "en",
        "promotion_target": "Everything",
    },
    "DE": {
        "customer_id": "1995608260",
        "final_url": "https://aeonathletics.de/collections/sale",
        "language_code": "de",
        "promotion_target": "Alles",
    },
    "SK": {
        "customer_id": "9217995931",
        "final_url": "https://aeonathletics.sk/collections/sale",
        "language_code": "sk",
        "promotion_target": "Všetko",
    },
    "CZ": {
        "customer_id": "8011554450",
        "final_url": "https://aeonathletics.cz/collections/sale",
        "language_code": "cs",
        "promotion_target": "Vše",
    },
    "SI": {
        "customer_id": "3972310409",
        "final_url": "https://aeonathletics.si/collections/sale",
        "language_code": "sl",
        "promotion_target": "Vse",
    },
}

COMMON = {
    "occasion": "BLACK_FRIDAY",
    "discount_modifier": "UP_TO",
    "percent_off_pct": 80,
    "redemption_start": "2026-11-10",
    "redemption_end": "2026-12-02",
}


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


def main():
    client = init_google_ads_client()

    results = []
    for market, cfg in MARKETS.items():
        cid = cfg["customer_id"]
        print(f"\n[{market}] {cid}")

        existing = fetch_existing_promotions(client, cid)
        if COMMON["occasion"] in existing:
            print(f"  skip BLACK_FRIDAY already exists")
            results.append((market, "skipped", None))
            continue

        promo = {**COMMON, **cfg}
        op = _build_promotion_operation(client, promo)

        svc = client.get_service("AssetService")
        req = client.get_type("MutateAssetsRequest")
        req.customer_id = cid
        req.operations.extend([op])
        req.partial_failure = True
        resp = svc.mutate_assets(request=req)

        failed = _parse_partial_failures(resp, [op])
        if 0 in failed or not resp.results[0].resource_name:
            print(f"  REJECTED")
            dump_errors(resp)
            results.append((market, "rejected", None))
            continue

        rn = resp.results[0].resource_name
        print(f"  created {rn}")

        linked, link_failed = link_at_account_level(
            client, cid, [rn], "PROMOTION",
            lambda i: f"BLACK_FRIDAY up-to-{promo['percent_off_pct']}% [{market}]"
        )
        if linked:
            results.append((market, "created+linked", rn))
        else:
            results.append((market, "created, link failed", rn))

    print("\n" + "=" * 60)
    print("SUMMARY")
    for market, status, rn in results:
        rn_str = f" -> {rn}" if rn else ""
        print(f"  {market}: {status}{rn_str}")
    print("=" * 60)


if __name__ == "__main__":
    main()
