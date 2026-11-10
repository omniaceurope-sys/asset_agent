"""
Finalise Medex Black Week 2026 — SI, HR, CZ, SK.

The 16 sitelinks + 16 promotion assets already exist (ids below). This script:

  1. Updates each sitelink with its scheduling start_date / end_date (the
     Vitality / Immunity / Activity / Black Friday week it belongs to).
  2. Links all 32 assets at the account level via CustomerAssetService.

Idempotent on both steps:
  - Update ops with a field mask are safe to re-apply.
  - Account-level links already present are detected and skipped.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Windows terminal encoding fallback for ✓ ✗ ⊘ etc.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from google.protobuf import field_mask_pb2  # noqa: E402

from google_ads_assets import init_google_ads_client  # noqa: E402

WEEKS = {
    "vitality":  ("2026-11-02", "2026-11-08"),
    "immunity":  ("2026-11-09", "2026-11-15"),
    "activity":  ("2026-11-16", "2026-11-22"),
    "blackfri":  ("2026-11-27", "2026-11-29"),
}

# Pre-created asset IDs — SITELINKS tagged with their week; PROMOTIONS unchanged.
ACCOUNTS = [
    {
        "id": "6465487333", "name": "Medex SI",
        "sitelinks": [
            ("vitality", "434354160377", "Črni teden vitalnosti"),
            ("immunity", "434459407789", "Črni teden imunosti"),
            ("activity", "434539273611", "Črni teden aktivnosti"),
            ("blackfri", "434354141186", "Črni petek"),
        ],
        "promos": [
            ("434539462743", "Izdelki za vitalnost"),
            ("434459759977", "Matični mleček"),
            ("434539887402", "Izdelki za aktivnost"),
            ("434460323479", "Medex izdelki"),
        ],
    },
    {
        "id": "4873324748", "name": "Medex HR",
        "sitelinks": [
            ("vitality", "434459460007", "Crni tjedan vitalnosti"),
            ("immunity", "434539291317", "Crni tjedan imuniteta"),
            ("activity", "434539290366", "Crni tjedan aktivnosti"),
            ("blackfri", "434459460019", "Black Friday"),
        ],
        "promos": [
            ("434355211004", "Proizvodi vitalnosti"),
            ("434540579598", "Matična mliječ"),
            ("434540732136", "Proizvodi aktivnosti"),
            ("434540682438", "Medex proizvodi"),
        ],
    },
    {
        "id": "5342656678", "name": "Medex CZ",
        "sitelinks": [
            ("vitality", "434539294413", "Černý týden vitality"),
            ("immunity", "434459462449", "Černý týden imunity"),
            ("activity", "434539291725", "Černý týden aktivity"),
            ("blackfri", "434354167658", "Black Friday"),
        ],
        "promos": [
            ("434355909740", "Produkty vitality"),
            ("434461458724", "Mateří kašička"),
            ("434541327216", "Produkty aktivity"),
            ("434356281989", "Produkty Medex"),
        ],
    },
    {
        "id": "8860201997", "name": "Medex SK",
        "sitelinks": [
            ("vitality", "434354168273", "Čierny týždeň vitality"),
            ("immunity", "434539294845", "Čierny týždeň imunity"),
            ("activity", "434539292127", "Čierny týždeň aktivity"),
            ("blackfri", "434354168276", "Black Friday"),
        ],
        "promos": [
            ("434541564663", "Produkty vitality"),
            ("434356510070", "Materská kašička"),
            ("434357051147", "Produkty aktivity"),
            ("434357423843", "Produkty Medex"),
        ],
    },
]


def existing_links(client, cid):
    """Return {asset_id: field_type.name} for existing SITELINK/PROMOTION account-level links."""
    ga = client.get_service("GoogleAdsService")
    q = ("SELECT customer_asset.asset, customer_asset.field_type "
         "FROM customer_asset "
         "WHERE customer_asset.field_type IN ('SITELINK','PROMOTION')")
    out = {}
    for r in ga.search(customer_id=cid, query=q):
        asset_id = r.customer_asset.asset.rsplit("/", 1)[-1]
        out[asset_id] = r.customer_asset.field_type.name
    return out


def sitelink_update_op(client, cid, asset_id, week):
    start, end = WEEKS[week]
    op = client.get_type("AssetOperation")
    op.update.resource_name = f"customers/{cid}/assets/{asset_id}"
    op.update.sitelink_asset.start_date = start
    op.update.sitelink_asset.end_date = end
    op.update_mask.CopyFrom(field_mask_pb2.FieldMask(
        paths=["sitelink_asset.start_date", "sitelink_asset.end_date"]
    ))
    return op


def link_op(client, cid, asset_id, field_type_str):
    op = client.get_type("CustomerAssetOperation")
    ca = op.create
    ca.asset = f"customers/{cid}/assets/{asset_id}"
    ca.field_type = getattr(client.enums.AssetFieldTypeEnum, field_type_str)
    return op


def main():
    client = init_google_ads_client()
    asset_svc = client.get_service("AssetService")
    ca_svc = client.get_service("CustomerAssetService")
    summary = []

    for acc in ACCOUNTS:
        cid = acc["id"]
        print(f"\nAccount: {cid} ({acc['name']})")

        # 1. Update sitelink scheduling dates
        print("  Updating sitelink dates...")
        update_ops, update_labels = [], []
        for week, asset_id, title in acc["sitelinks"]:
            start, end = WEEKS[week]
            update_ops.append(sitelink_update_op(client, cid, asset_id, week))
            update_labels.append(f"{title}  →  {start} → {end}")

        updated = 0
        try:
            asset_svc.mutate_assets(customer_id=cid, operations=update_ops)
            for label in update_labels:
                print(f"    ✓ {label}")
            updated = len(update_ops)
        except Exception as e:
            print(f"    ✗ Sitelink update failed — {e}")

        # 2. Account-level linking (skip ones already linked)
        print("  Linking at account level...")
        try:
            already = existing_links(client, cid)
        except Exception as e:
            print(f"    ✗ Could not read existing links — {e}")
            summary.append((acc["name"], updated, 0, "link read failed"))
            continue

        link_ops, link_labels = [], []
        for week, asset_id, title in acc["sitelinks"]:
            if asset_id in already:
                print(f"    ⊘ Sitelink '{title}' already linked")
                continue
            link_ops.append(link_op(client, cid, asset_id, "SITELINK"))
            link_labels.append(f"SITELINK  {title}")
        for asset_id, target in acc["promos"]:
            if asset_id in already:
                print(f"    ⊘ Promotion '{target}' already linked")
                continue
            link_ops.append(link_op(client, cid, asset_id, "PROMOTION"))
            link_labels.append(f"PROMOTION {target}")

        if not link_ops:
            print("    (nothing to link)")
            summary.append((acc["name"], updated, 0, "all already linked"))
            continue

        try:
            ca_svc.mutate_customer_assets(customer_id=cid, operations=link_ops)
            for label in link_labels:
                print(f"    ✓ linked {label}")
            summary.append((acc["name"], updated, len(link_ops), "ok"))
        except Exception as e:
            print(f"    ✗ Linking failed — {e}")
            summary.append((acc["name"], updated, 0, "link failed"))

    print("\nSUMMARY")
    for name, updated, linked, status in summary:
        print(f"  {name}: {updated} sitelink dates set, {linked} assets linked ({status})")


if __name__ == "__main__":
    main()
