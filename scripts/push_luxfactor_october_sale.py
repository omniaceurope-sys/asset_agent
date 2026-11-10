"""
One-off push for the Lux-Factor October sale (15 % off everything, code 15LUX) — SI, CZ, SK, HU.

1. Pauses the account-level links of the hand-cream promo assets (see push_luxfactor_handcream.py).
2. Per account: creates 1 sitelink + 1 promotion asset scheduled 2026-10-21 → 2026-10-30
   and links them at account level. Skips an asset if the same text already exists.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from google.protobuf import field_mask_pb2  # noqa: E402

from google_ads_assets import init_google_ads_client  # noqa: E402
from push_luxfactor_handcream import existing_texts, link_ops  # noqa: E402

START = "2026-10-21"
END = "2026-10-30"
CODE = "15LUX"
B = "https://luxfactor.com"

# Hand-cream asset IDs created on 2026-10-09: (sitelink, promotion)
HANDCREAM = {
    "6528403835": ("428680803392", "428868954780"),
    "5098995327": ("428868965784", "428680806365"),
    "7548207539": ("428868973347", "428868977847"),
    "6801684196": ("428680818275", "428868982551"),
}

ACCOUNTS = [
    {"id": "6528403835", "name": "Lux-Factor - SI", "lang": "sl", "url": f"{B}/sl-si/october-sale",
     "sitelink": ("15 % popusta na vse", "S kodo 15LUX v košarici", "Akcija velja do 30. 10."),
     "target": "Vse Lux izdelke"},
    {"id": "5098995327", "name": "Lux-Factor CZ", "lang": "cs", "url": f"{B}/cs-cz/october-sale",
     "sitelink": ("Sleva 15 % na vše", "S kódem 15LUX v košíku", "Akce platí do 30. 10."),
     "target": "Všechny Lux produkty"},
    {"id": "7548207539", "name": "Lux-Factor - SK", "lang": "sk", "url": f"{B}/sk-sk/october-sale",
     "sitelink": ("Zľava 15 % na všetko", "S kódom 15LUX v košíku", "Akcia platí do 30. 10."),
     "target": "Všetky Lux produkty"},
    {"id": "6801684196", "name": "Lux-Factor HU", "lang": "hu", "url": f"{B}/hu-hu/october-sale",
     "sitelink": ("15% kedvezmény mindenre", "A 15LUX kóddal a kosárban", "Az akció október 30-ig tart"),
     "target": "Minden Lux termék"},
]


def existing_promos(client, cid):
    """Set of (target, percent_off, code) for existing promotions — target alone is too loose,
    old promos (e.g. SPRING20) reuse the same item text."""
    ga = client.get_service("GoogleAdsService")
    q = """SELECT asset.promotion_asset.promotion_target, asset.promotion_asset.percent_off,
                  asset.promotion_asset.promotion_code
           FROM asset WHERE asset.type = 'PROMOTION'"""
    return {
        (r.asset.promotion_asset.promotion_target.lower(), r.asset.promotion_asset.percent_off,
         r.asset.promotion_asset.promotion_code.upper())
        for r in ga.search(customer_id=cid, query=q)
    }


def pause_handcream(client, ca_svc, cid):
    sl_id, pr_id = HANDCREAM[cid]
    ops = []
    for asset_id, ft in ((sl_id, "SITELINK"), (pr_id, "PROMOTION")):
        op = client.get_type("CustomerAssetOperation")
        op.update.resource_name = f"customers/{cid}/customerAssets/{asset_id}~{ft}"
        op.update.status = client.enums.AssetLinkStatusEnum.PAUSED
        op.update_mask.CopyFrom(field_mask_pb2.FieldMask(paths=["status"]))
        ops.append(op)
    ca_svc.mutate_customer_assets(customer_id=cid, operations=ops)


def sitelink_op(client, acc):
    op = client.get_type("AssetOperation")
    a = op.create
    title, d1, d2 = acc["sitelink"]
    a.sitelink_asset.link_text = title
    a.sitelink_asset.description1 = d1
    a.sitelink_asset.description2 = d2
    a.sitelink_asset.start_date = START
    a.sitelink_asset.end_date = END
    a.final_urls.append(acc["url"])
    return op


def promo_op(client, acc):
    op = client.get_type("AssetOperation")
    a = op.create
    pa = a.promotion_asset
    pa.promotion_target = acc["target"]
    pa.percent_off = 150_000  # 15 % (1,000,000 = 100 %)
    pa.promotion_code = CODE
    pa.language_code = acc["lang"]
    pa.start_date = START
    pa.end_date = END
    a.final_urls.append(acc["url"])
    return op


def main():
    client = init_google_ads_client()
    asset_svc = client.get_service("AssetService")
    ca_svc = client.get_service("CustomerAssetService")
    summary = []

    for acc in ACCOUNTS:
        cid = acc["id"]
        print(f"\nAccount: {cid} ({acc['name']})")

        try:
            pause_handcream(client, ca_svc, cid)
            print("  ⏸ Paused hand-cream sitelink + promotion")
            paused = "paused"
        except Exception as e:
            print(f"  ✗ Pausing hand-cream assets failed — {e}")
            paused = "pause FAILED"

        sl_existing, _ = existing_texts(client, cid)
        pr_existing = existing_promos(client, cid)
        ops, labels = [], []
        if acc["sitelink"][0].lower() in sl_existing:
            print(f"  ⊘ Sitelink '{acc['sitelink'][0]}' (already exists)")
        else:
            ops.append(sitelink_op(client, acc)); labels.append(("SITELINK", f"Sitelink: {acc['sitelink'][0]}"))
        if (acc["target"].lower(), 150_000, CODE) in pr_existing:
            print(f"  ⊘ Promotion '{acc['target']}' (already exists)")
        else:
            ops.append(promo_op(client, acc)); labels.append(("PROMOTION", f"Promotion: 15% {acc['target']} ({CODE})"))

        if not ops:
            summary.append((acc["name"], paused, 0, 0, "all skipped"))
            continue

        try:
            resp = asset_svc.mutate_assets(customer_id=cid, operations=ops)
        except Exception as e:
            print(f"  ✗ Asset creation failed — {e}")
            summary.append((acc["name"], paused, 0, 0, "create failed"))
            continue

        rns = [r.resource_name for r in resp.results]
        for (_, label), rn in zip(labels, rns):
            print(f"  ✓ {label}  [{rn}]")

        try:
            ca_svc.mutate_customer_assets(
                customer_id=cid,
                operations=link_ops(client, [(rn, ft) for rn, (ft, _) in zip(rns, labels)]),
            )
            print(f"  ✓ Linked {len(rns)} asset(s) at account level")
            summary.append((acc["name"], paused, len(rns), len(rns), "ok"))
        except Exception as e:
            print(f"  ✗ Account-level linking failed — {e}")
            summary.append((acc["name"], paused, len(rns), 0, "link failed"))

    print("\nSUMMARY")
    for name, paused, created, linked, status in summary:
        print(f"  {name}: hand-cream {paused}; created {created}, linked {linked} ({status})")


if __name__ == "__main__":
    main()
