"""
Upload the Aeon diamond logo PNG to both UK (450-900-0147) and US
(547-758-0929) accounts' shared image library.

Google Ads has strict min dimensions for business logos:
  LOGO (square 1:1): >= 128x128
  LANDSCAPE_LOGO (4:1): >= 512x128

Business logos cannot be linked via CustomerAsset (we proved that already —
UNSUPPORTED_FIELD_TYPE). The image sits in the shared library ready to be
picked up by PMax asset groups or the Business identity UI.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from google_ads_assets import init_google_ads_client, _parse_partial_failures  # noqa: E402

UK = "4509000147"
US = "5477580929"

SOURCE_IMAGE = Path(
    r"C:\Users\miroh\AppData\Local\Temp\claude\2f37f7677493b616"
    r"\ad1519ae-6c2a-4494-9980-b838aa5d4558\images\2.png"
)
ASSET_NAME = "Aeon_diamond_logo.png"


def upload_image(client, customer_id: str, image_bytes: bytes, name: str):
    op = client.get_type("AssetOperation")
    asset = op.create
    asset.name = name
    asset.type_ = client.enums.AssetTypeEnum.IMAGE
    asset.image_asset.data = image_bytes

    svc = client.get_service("AssetService")
    req = client.get_type("MutateAssetsRequest")
    req.customer_id = customer_id
    req.operations.extend([op])
    req.partial_failure = True
    resp = svc.mutate_assets(request=req)

    failed = _parse_partial_failures(resp, [op])
    if 0 in failed or not resp.results[0].resource_name:
        print(f"  [{customer_id}] X upload rejected")
        if resp.partial_failure_error and resp.partial_failure_error.details:
            from google.ads.googleads.v24.errors.types.errors import GoogleAdsFailure  # noqa: PLC0415
            for detail in resp.partial_failure_error.details:
                failure = GoogleAdsFailure()
                failure_pb = type(failure).pb(failure)
                detail.Unpack(failure_pb)
                failure = type(failure).wrap(failure_pb)
                for err in failure.errors:
                    print(f"    err: {err.message}")
        return None
    rn = resp.results[0].resource_name
    print(f"  [{customer_id}] OK uploaded {name} -> {rn}")
    return rn


def main():
    if not SOURCE_IMAGE.exists():
        sys.exit(f"ERROR: source image not found at {SOURCE_IMAGE}")
    image_bytes = SOURCE_IMAGE.read_bytes()
    print(f"Source: {SOURCE_IMAGE.name}  ({len(image_bytes)} bytes)")

    client = init_google_ads_client()
    for cid in (UK, US):
        upload_image(client, cid, image_bytes, ASSET_NAME)


if __name__ == "__main__":
    main()
