"""
Re-push only the Black Friday promotion asset to UK and US after fixing
percent_off scaling (1,000,000 micros == 100%, so 80% == 800,000).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from google_ads_assets import init_google_ads_client, _parse_partial_failures  # noqa: E402
from push_aeon_uk_us import (  # noqa: E402
    MARKETS, build_content, _build_promotion_operation,
    link_at_account_level, fetch_existing_promotions,
)


def main():
    client = init_google_ads_client()
    for market, cfg in MARKETS.items():
        customer_id = cfg["customer_id"]
        content = build_content(market)
        promo = content["promotion"]
        print(f"\n[{market.upper()}] {customer_id} — Black Friday promo")

        existing_promos = fetch_existing_promotions(client, customer_id)
        if promo["occasion"] in existing_promos:
            print(f"  ⊘ BLACK_FRIDAY already exists — skipping")
            continue

        op = _build_promotion_operation(client, promo)
        svc = client.get_service("AssetService")
        req = client.get_type("MutateAssetsRequest")
        req.customer_id = customer_id
        req.operations.extend([op])
        req.partial_failure = True
        resp = svc.mutate_assets(request=req)

        failed = _parse_partial_failures(resp, [op])
        if 0 in failed or not resp.results[0].resource_name:
            print(f"  ✗ Promotion asset rejected")
            # Dump error detail
            if resp.partial_failure_error and resp.partial_failure_error.details:
                from google.ads.googleads.v24.errors.types.errors import GoogleAdsFailure  # noqa: PLC0415
                for detail in resp.partial_failure_error.details:
                    failure = GoogleAdsFailure()
                    failure_pb = type(failure).pb(failure)
                    detail.Unpack(failure_pb)
                    failure = type(failure).wrap(failure_pb)
                    for err in failure.errors:
                        print(f"    err: {err.message}")
            continue

        asset_rn = resp.results[0].resource_name
        print(f"  ✓ Created promotion asset {asset_rn}")

        linked, link_failed = link_at_account_level(
            client, customer_id, [asset_rn], "PROMOTION",
            lambda i: f"BLACK_FRIDAY up-to-{promo['percent_off_pct']}%"
        )
        print(f"  linked at account level: {linked} (failed: {link_failed})")


if __name__ == "__main__":
    main()
