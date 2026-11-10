"""Create & link the Dorin sijaj BF 2026 promo, ignoring last year's expired
BLACK_FRIDAY asset (309144675715, ended 2025-11-30, not linked anyway)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from google_ads_assets import init_google_ads_client, _parse_partial_failures  # noqa: E402
from push_aeon_uk_us import _build_promotion_operation, link_at_account_level  # noqa: E402

CID = "9043256297"
PROMO = {
    "occasion": "BLACK_FRIDAY",
    "discount_modifier": "UP_TO",
    "percent_off_pct": 63,
    "promotion_target": "Čistila in seti",
    "language_code": "sl",
    "redemption_start": "2026-11-10",
    "redemption_end": "2026-12-02",
    "final_url": "https://dorinsijaj.si/blackfriday/",
}


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


def main():
    client = init_google_ads_client()
    op = _build_promotion_operation(client, PROMO)
    svc = client.get_service("AssetService")
    req = client.get_type("MutateAssetsRequest")
    req.customer_id = CID
    req.operations.extend([op])
    req.partial_failure = True
    resp = svc.mutate_assets(request=req)
    failed = _parse_partial_failures(resp, [op])
    if 0 in failed or not resp.results[0].resource_name:
        print("REJECTED")
        dump(resp)
        return
    rn = resp.results[0].resource_name
    print(f"created {rn}")
    linked, link_failed = link_at_account_level(
        client, CID, [rn], "PROMOTION",
        lambda i: f"BLACK_FRIDAY up-to-{PROMO['percent_off_pct']}%"
    )
    print(f"linked: {linked}  failed: {link_failed}")


if __name__ == "__main__":
    main()
