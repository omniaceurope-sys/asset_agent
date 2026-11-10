"""
Lux-Factor — November Sale 2026 (2026-11-09 → 2026-11-18)

Account-level push to SI / CZ / SK / HU: 4 sitelinks + 1 promotion per account,
all pointing at the market's /november-2026 landing page.

Reuses the helpers from push_heroclothing_blackfriday (build + reconcile + link).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import push_heroclothing_blackfriday as hero  # noqa: E402
from google_ads_assets import init_google_ads_client  # noqa: E402

# Override schedule for this push (module-level globals in hero).
hero.START_DATE = "2026-11-09"
hero.END_DATE = "2026-11-18"

B = "https://luxfactor.com"


def sl(t, d1, d2, url):
    return {"title": t, "description1": d1, "description2": d2, "final_url": url}


def promo(target, lang, url):
    return {
        "target": target,
        "language": lang,
        "final_url": url,
        "percent_off": 44,
        "discount_modifier": "UP_TO",
        "occasion": "FALL_SALE",
    }


ACCOUNTS = [
    {
        "id": "6528403835", "name": "Lux-Factor SI",
        "url": f"{B}/sl-si/november-2026",
        "bundle": {
            "sitelinks": [
                sl("Novembrska akcija do -44%", "Do 44 % popusta na komplete", "Velja do 18. 11. 2026",
                   f"{B}/sl-si/november-2026"),
                sl("4D HYALURON komplet", "Mlajši videz že po prvi uporabi", "Prihranite do 44 %",
                   f"{B}/sl-si/november-2026"),
                sl("4D CAVIAR komplet", "Kaviarjev izvleček za zrelo kožo", "Prihranite do 44 %",
                   f"{B}/sl-si/november-2026"),
                sl("30-dnevna garancija", "Vrnitev denarja brez vprašanj", "Brezplačna dostava nad 44 €",
                   f"{B}/sl-si/november-2026"),
            ],
            "promotions": [
                promo("Lux-Factor komplete", "sl", f"{B}/sl-si/november-2026"),
            ],
        },
    },
    {
        "id": "5098995327", "name": "Lux-Factor CZ",
        "url": f"{B}/cs-cz/november-2026",
        "bundle": {
            "sitelinks": [
                sl("November sale", "Sleva až 44 % na balíčky péče", "Platí do 18. 11. 2026",
                   f"{B}/cs-cz/november-2026"),
                sl("4D HYALURON balíček", "Mladší vzhled po první aplikaci", "Ušetříte až 44 %",
                   f"{B}/cs-cz/november-2026"),
                sl("4D CAVIAR balíček", "Kaviárový extrakt pro zralou pleť", "Ušetříte až 44 %",
                   f"{B}/cs-cz/november-2026"),
                sl("30denní záruka", "Vrácení peněz bez otázek", "Doprava zdarma nad 1 300 Kč",
                   f"{B}/cs-cz/november-2026"),
            ],
            "promotions": [
                promo("Lux-Factor balíčky", "cs", f"{B}/cs-cz/november-2026"),
            ],
        },
    },
    {
        "id": "7548207539", "name": "Lux-Factor SK",
        "url": f"{B}/sk-sk/november-2026",
        "bundle": {
            "sitelinks": [
                sl("November sale", "Zľava až 44 % na balíčky", "Platí do 18. 11. 2026",
                   f"{B}/sk-sk/november-2026"),
                sl("4D HYALURON balíček", "Mladší vzhľad po prvom použití", "Ušetríte až 44 %",
                   f"{B}/sk-sk/november-2026"),
                sl("4D CAVIAR balíček", "Kaviárový extrakt pre zrelú pleť", "Ušetríte až 44 %",
                   f"{B}/sk-sk/november-2026"),
                sl("30-dňová záruka", "Vrátenie peňazí bez otázok", "Doprava zdarma nad 50 €",
                   f"{B}/sk-sk/november-2026"),
            ],
            "promotions": [
                promo("Lux-Factor balíčky", "sk", f"{B}/sk-sk/november-2026"),
            ],
        },
    },
    {
        "id": "6801684196", "name": "Lux-Factor HU",
        "url": f"{B}/hu-hu/november-2026",
        "bundle": {
            "sitelinks": [
                sl("November sale", "Akár 44% kedvezmény csomagokra", "2026. 11. 18-ig érvényes",
                   f"{B}/hu-hu/november-2026"),
                sl("4D HYALURON csomag", "Fiatalabb bőr első használatra", "Spórolj akár 44%",
                   f"{B}/hu-hu/november-2026"),
                sl("4D CAVIAR csomag", "Kaviár kivonat érett bőrre", "Spórolj akár 44%",
                   f"{B}/hu-hu/november-2026"),
                sl("30 napos garancia", "Pénzvisszafizetési garancia", "Ingyenes szállítás 16 000 Ft felett",
                   f"{B}/hu-hu/november-2026"),
            ],
            "promotions": [
                promo("Lux-Factor csomagok", "hu", f"{B}/hu-hu/november-2026"),
            ],
        },
    },
]


def main():
    client = init_google_ads_client()
    results = []
    for acc in ACCOUNTS:
        results.append(hero.run_account_level(client, acc["id"], acc["name"], acc["bundle"]))

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for r in results:
        sc, sr, sf, sl_l, sl_lf = r["sitelinks"]
        pc, pr_, pf, pl_, plf = r["promotions"]
        print(f"\n{r['name']} ({r['cid']})")
        print(f"  sitelinks:  create {sc} / reuse {sr} / create-fail {sf}; "
              f"linked {sl_l} ({sl_lf} link-fail)")
        print(f"  promotions: create {pc} / reuse {pr_} / create-fail {pf}; "
              f"linked {pl_} ({plf} link-fail)")

    print(f"\nSchedule on every asset: {hero.START_DATE} → {hero.END_DATE}")


if __name__ == "__main__":
    main()
