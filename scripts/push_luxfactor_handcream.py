"""
One-off push for the Lux-Factor autumn hand-cream promo (SI, CZ, SK, HU).

Per account: 1 sitelink + 1 promotion asset, both scheduled 2026-10-09 → 2026-10-31,
created via AssetService and linked at account level via CustomerAssetService.
Skips an asset if one with the same sitelink text / promotion target already exists.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from google_ads_assets import init_google_ads_client  # noqa: E402

START = "2026-10-09"
END = "2026-10-31"
B = "https://luxfactor.com"

ACCOUNTS = [
    {"id": "6528403835", "name": "Lux-Factor - SI", "lang": "sl", "url": f"{B}/sl-si/free-hand-cream",
     "sitelink": ("10 % popusta na vse", "+ krema za roke gratis", "Ob naročilu nad 30 €"),
     "promo": {"target": "Celo naročilo", "currency": "EUR", "min_order": 30}},
    {"id": "5098995327", "name": "Lux-Factor CZ", "lang": "cs", "url": f"{B}/cs-cz/free-hand-cream",
     "sitelink": ("Sleva 10 % na vše", "+ krém na ruce zdarma", "K objednávce nad 750 Kč"),
     "promo": {"target": "Krém na ruce zdarma", "currency": "CZK", "min_order": 750}},
    {"id": "7548207539", "name": "Lux-Factor - SK", "lang": "sk", "url": f"{B}/sk-sk/free-hand-cream",
     "sitelink": ("Zľava 10 % na všetko", "+ krém na ruky zadarmo", "K objednávke nad 30 €"),
     "promo": {"target": "Krém na ruky zadarmo", "currency": "EUR", "min_order": 30}},
    {"id": "6801684196", "name": "Lux-Factor HU", "lang": "hu", "url": f"{B}/hu-hu/free-hand-cream",
     "sitelink": ("10% kedvezmény mindenre", "+ ingyenes kézkrém", "12 000 Ft feletti rendelésre"),
     "promo": {"target": "Ingyenes kézkrém", "currency": "HUF", "min_order": 12000}},
]


def existing_texts(client, cid):
    ga = client.get_service("GoogleAdsService")
    q = """SELECT asset.type, asset.sitelink_asset.link_text, asset.promotion_asset.promotion_target
           FROM asset WHERE asset.type IN ('SITELINK', 'PROMOTION')"""
    sl, pr = set(), set()
    for row in ga.search(customer_id=cid, query=q):
        if row.asset.sitelink_asset.link_text:
            sl.add(row.asset.sitelink_asset.link_text.lower())
        if row.asset.promotion_asset.promotion_target:
            pr.add(row.asset.promotion_asset.promotion_target.lower())
    return sl, pr


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
    p = acc["promo"]
    pa = a.promotion_asset
    pa.promotion_target = p["target"]
    pa.percent_off = 100_000  # 10 % (1,000,000 = 100 %)
    pa.orders_over_amount.currency_code = p["currency"]
    pa.orders_over_amount.amount_micros = p["min_order"] * 1_000_000
    pa.language_code = acc["lang"]
    pa.start_date = START
    pa.end_date = END
    a.final_urls.append(acc["url"])
    return op


def link_ops(client, rns_types):
    ops = []
    for rn, ft in rns_types:
        op = client.get_type("CustomerAssetOperation")
        op.create.asset = rn
        op.create.field_type = getattr(client.enums.AssetFieldTypeEnum, ft)
        ops.append(op)
    return ops


def main():
    client = init_google_ads_client()
    asset_svc = client.get_service("AssetService")
    ca_svc = client.get_service("CustomerAssetService")
    summary = []

    for acc in ACCOUNTS:
        cid = acc["id"]
        print(f"\nAccount: {cid} ({acc['name']})")
        sl_existing, pr_existing = existing_texts(client, cid)

        ops, labels = [], []
        if acc["sitelink"][0].lower() in sl_existing:
            print(f"  ⊘ Sitelink '{acc['sitelink'][0]}' (already exists)")
        else:
            ops.append(sitelink_op(client, acc)); labels.append(("SITELINK", f"Sitelink: {acc['sitelink'][0]}"))
        if acc["promo"]["target"].lower() in pr_existing:
            print(f"  ⊘ Promotion '{acc['promo']['target']}' (already exists)")
        else:
            ops.append(promo_op(client, acc)); labels.append(("PROMOTION", f"Promotion: 10% {acc['promo']['target']}"))

        if not ops:
            summary.append((acc["name"], 0, 0, "all skipped"))
            continue

        try:
            resp = asset_svc.mutate_assets(customer_id=cid, operations=ops)
        except Exception as e:
            print(f"  ✗ Asset creation failed — {e}")
            summary.append((acc["name"], 0, 0, "create failed"))
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
            summary.append((acc["name"], len(rns), len(rns), "ok"))
        except Exception as e:
            print(f"  ✗ Account-level linking failed — {e}")
            summary.append((acc["name"], len(rns), 0, "link failed"))

    print("\nSUMMARY")
    for name, created, linked, status in summary:
        print(f"  {name}: created {created}, linked {linked} ({status})")


if __name__ == "__main__":
    main()
