"""
Diagnose why the Black Friday promotion asset and the logo account-link
were rejected on UK and US. Prints full error details.
"""
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent))

from google_ads_assets import init_google_ads_client  # noqa: E402

UK = "4509000147"
US = "5477580929"


def print_errors(response, label):
    pfe = response.partial_failure_error
    if not pfe or not pfe.details:
        print(f"  {label}: no partial_failure_error details")
        return
    from google.ads.googleads.v24.errors.types.errors import GoogleAdsFailure  # noqa: PLC0415
    for detail in pfe.details:
        # proto-plus wrapper: use pb() for the raw protobuf
        failure = GoogleAdsFailure()
        failure_pb = type(failure).pb(failure)
        detail.Unpack(failure_pb)
        failure = type(failure).wrap(failure_pb)
        for err in failure.errors:
            # Dump the whole error for maximum signal
            print(f"  {label} ✗ {err}")


def try_promotion(client, customer_id):
    op = client.get_type("AssetOperation")
    asset = op.create
    pa = asset.promotion_asset
    pa.occasion = client.enums.PromotionExtensionOccasionEnum.BLACK_FRIDAY
    pa.discount_modifier = client.enums.PromotionExtensionDiscountModifierEnum.UP_TO
    pa.percent_off = 80_000_000           # 80% in micros
    pa.promotion_target = "Everything"
    pa.language_code = "en"
    pa.redemption_start_date = "2026-11-10"
    pa.redemption_end_date = "2026-12-02"
    cc = "GB" if customer_id == UK else "US"
    asset.final_urls.append(f"https://aeonathletics.com/collections/sale?country={cc}")

    asset_service = client.get_service("AssetService")
    request = client.get_type("MutateAssetsRequest")
    request.customer_id = customer_id
    request.operations.extend([op])
    request.partial_failure = True
    response = asset_service.mutate_assets(request=request)
    print(f"Promotion on {customer_id}: results={[r.resource_name for r in response.results]}")
    print_errors(response, "promotion")
    return response.results[0].resource_name if response.results and response.results[0].resource_name else None


def find_logo_asset(client, customer_id):
    """Find the already-uploaded Aeon_black.png IMAGE asset in the account."""
    ga = client.get_service("GoogleAdsService")
    q = """
        SELECT asset.resource_name, asset.name, asset.image_asset.file_size,
               asset.image_asset.full_size.width_pixels,
               asset.image_asset.full_size.height_pixels
        FROM asset
        WHERE asset.type = 'IMAGE' AND asset.name = 'Aeon_black.png'
    """
    for batch in ga.search_stream(customer_id=customer_id, query=q):
        for row in batch.results:
            print(f"  logo found: {row.asset.resource_name} "
                  f"size={row.asset.image_asset.file_size}B "
                  f"{row.asset.image_asset.full_size.width_pixels}x"
                  f"{row.asset.image_asset.full_size.height_pixels}")
            return row.asset.resource_name
    return None


def try_logo_link(client, customer_id, asset_rn, field_type_str):
    ca_op = client.get_type("CustomerAssetOperation")
    ca = ca_op.create
    ca.asset = asset_rn
    ca.field_type = getattr(client.enums.AssetFieldTypeEnum, field_type_str)

    svc = client.get_service("CustomerAssetService")
    req = client.get_type("MutateCustomerAssetsRequest")
    req.customer_id = customer_id
    req.operations.extend([ca_op])
    req.partial_failure = True
    resp = svc.mutate_customer_assets(request=req)
    results = [r.resource_name for r in resp.results]
    print(f"Link {field_type_str} on {customer_id}: results={results}")
    print_errors(resp, f"link {field_type_str}")


def main():
    client = init_google_ads_client()
    for cid in (UK, US):
        print("\n" + "=" * 60)
        print(f"ACCOUNT {cid}")
        print("=" * 60)
        try_promotion(client, cid)
        print()
        logo_rn = find_logo_asset(client, cid)
        if logo_rn:
            # Try LOGO first, then LANDSCAPE_LOGO
            try_logo_link(client, cid, logo_rn, "LOGO")
            try_logo_link(client, cid, logo_rn, "LANDSCAPE_LOGO")


if __name__ == "__main__":
    main()
