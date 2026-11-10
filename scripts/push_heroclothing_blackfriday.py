"""
HERO Clothing — Black Friday 2026 (2026-11-05 → 2026-11-30)

Pushes sitelinks + promotion assets to four accounts:

  - HERO EU  (5007494125)  — CAMPAIGN level on six brand campaigns (HR/HU/DE/BG/GR/RO)
  - HERO CZ  (5753392380)  — ACCOUNT level
  - HERO SK  (8145516592)  — ACCOUNT level
  - HERO PL  (6718552884)  — ACCOUNT level

For each target asset:
  - if an asset with matching identity already exists in the account → reuse its resource_name
  - else create via AssetService (with start_date / end_date baked in)
Then link every resource_name at the correct level (customer_asset or campaign_asset).

Idempotent: re-running skips assets that are already linked at that level.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Windows terminal UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from google_ads_assets import init_google_ads_client, _parse_partial_failures  # noqa: E402

START_DATE = "2026-11-05"
END_DATE = "2026-11-30"

# ----------------------------------------------------------------------------
# Data — exactly what the user approved in the preview
# ----------------------------------------------------------------------------

def sl(title, d1, d2, url):
    return {"title": title, "description1": d1, "description2": d2, "final_url": url}


def promo(target, lang, url, percent_off=60):
    return {
        "target": target,
        "language": lang,
        "final_url": url,
        "percent_off": percent_off,
        "discount_modifier": "UP_TO",
        "occasion": "BLACK_FRIDAY",
    }


HERO_EU_CAMPAIGNS = {
    "|HR|-Search-Brand-[Bid:mClicks-0.08]": {
        "sitelinks": [
            sl("Black Friday Sale", "Popusti do -60% na sve", "Samo do 30.11. – kupi sada",
               "https://heroclothing.eu/hr-hr/collections/sale"),
            sl("Black Friday Pack", "Najisplativiji HERO paket", "Majice, bokserice i čarape",
               "https://heroclothing.eu/hr-hr/products/black-friday-pack"),
            sl("Majice do -60%", "Paketi majica na akciji", "Odaberi boje i veličine",
               "https://heroclothing.eu/hr-hr/collections/t-shirts"),
            sl("Bokserice 8+7 gratis", "Kupi više, uštedi više", "Udobne HERO bokserice",
               "https://heroclothing.eu/hr-hr/collections/boxers"),
        ],
        "promotions": [
            promo("Muška odjeća", "hr", "https://heroclothing.eu/hr-hr/collections/sale"),
        ],
    },
    "|HU|-Search-Brand-[Bid:mClicks-0.06]": {
        "sitelinks": [
            sl("Black Friday Akció", "Akár -60% minden termékre", "Csak 11.30-ig – vásárolj most",
               "https://heroclothing.eu/hu-hu/collections/kiarusitas"),
            sl("Black Friday Pack", "A legkedvezőbb HERO csomag", "Pólók, boxerek és zoknik",
               "https://heroclothing.eu/hu-hu/products/black-friday-pack"),
            sl("Pólók akár -60%", "Póló csomagok akciósan", "Válassz színt és méretet",
               "https://heroclothing.eu/hu-hu/collections/polok"),
            sl("HERO boxerek", "Vegyél többet, spórolj többet", "Kényelmes férfi boxerek",
               "https://heroclothing.eu/hu-hu/collections/boxerek"),
        ],
        "promotions": [
            promo("Férfi ruházat", "hu", "https://heroclothing.eu/hu-hu/collections/kiarusitas"),
        ],
    },
    "|DE|-Search-Brand-[Bid:mClicks-0.20]": {
        "sitelinks": [
            sl("Black Friday Sale", "Bis zu 60 % Rabatt auf alles", "Nur bis 30.11. – jetzt shoppen",
               "https://heroclothing.eu/de-de/collections/sale"),
            sl("Black Friday Pack", "Das beste HERO Spar-Paket", "T-Shirts, Boxer & Socken",
               "https://heroclothing.eu/de-de/products/black-friday-pack"),
            sl("T-Shirts bis -60 %", "T-Shirt-Packs im Angebot", "Farben & Größen frei wählbar",
               "https://heroclothing.eu/de-de/collections/t-shirts"),
            sl("Boxer bis 8+7 gratis", "Mehr kaufen, mehr sparen", "Bequeme HERO Boxershorts",
               "https://heroclothing.eu/de-de/collections/boxers"),
        ],
        "promotions": [
            promo("Herren-Basics", "de", "https://heroclothing.eu/de-de/collections/sale"),
        ],
    },
    "|BG|-Search-Brand-[Bid:mClicks-0.10]": {
        "sitelinks": [
            sl("Black Friday разпродажба", "До 60% отстъпка на всичко", "Само до 30.11 – поръчай сега",
               "https://heroclothing.eu/bg-bg/collections/sale"),
            sl("Black Friday Pack", "Най-изгодният пакет HERO", "Тениски, боксерки и чорапи",
               "https://heroclothing.eu/bg-bg/products/black-friday-pack"),
            sl("Тениски до -60%", "Пакети тениски на промо", "Избери цветове и размери",
               "https://heroclothing.eu/bg-bg/collections/t-shirts"),
            sl("Боксерки 8+7 безплатно", "Купи повече, спести повече", "Удобни боксерки HERO",
               "https://heroclothing.eu/bg-bg/collections/boxers"),
        ],
        "promotions": [
            promo("Мъжки дрехи", "bg", "https://heroclothing.eu/bg-bg/collections/sale"),
        ],
    },
    "|GR|-Search-Brand-[Bid:mClicks-0.10]": {
        "sitelinks": [
            sl("Black Friday Sale", "Έως 60% έκπτωση σε όλα", "Μόνο έως 30/11 – αγόρασε τώρα",
               "https://heroclothing.eu/el-gr/collections/sale"),
            sl("Black Friday Pack", "Το πιο συμφέρον πακέτο HERO", "T-shirts, μποξεράκια, κάλτσες",
               "https://heroclothing.eu/el-gr/products/black-friday-pack"),
            sl("T-shirts έως -60%", "Πακέτα t-shirts σε προσφορά", "Διάλεξε χρώματα και μεγέθη",
               "https://heroclothing.eu/el-gr/collections/t-shirts"),
            sl("Μποξεράκια HERO", "Αγόρασε περισσότερα, κέρδισε", "Άνετα ανδρικά μποξεράκια",
               "https://heroclothing.eu/el-gr/collections/boxers"),
        ],
        "promotions": [
            promo("Ανδρικά ρούχα", "el", "https://heroclothing.eu/el-gr/collections/sale"),
        ],
    },
    "|RO|-Search-Brand-[Bid:mClicks-0.10]": {
        "sitelinks": [
            sl("Black Friday Reduceri", "Până la -60% la tot magazinul", "Doar până pe 30.11 – comandă",
               "https://heroclothing.eu/ro-ro/collections/sale"),
            sl("Black Friday Pack", "Cel mai avantajos pachet HERO", "Tricouri, boxeri și șosete",
               "https://heroclothing.eu/ro-ro/products/black-friday-pack"),
            sl("Tricouri până la -60%", "Pachete de tricouri la ofertă", "Alege culorile și mărimile",
               "https://heroclothing.eu/ro-ro/collections/t-shirts"),
            sl("Boxeri 8+7 gratuit", "Cumperi mai mult, economisești", "Boxeri comozi HERO",
               "https://heroclothing.eu/ro-ro/collections/boxers"),
        ],
        "promotions": [
            promo("Haine bărbați", "ro", "https://heroclothing.eu/ro-ro/collections/sale"),
        ],
    },
}

HERO_CZ = {
    "sitelinks": [
        sl("Black Friday výprodej", "Slevy až 60 % na celý e-shop", "Jen do 30. 11. – nakupte teď",
           "https://heroclothing.cz/collections/sale"),
        sl("Black Friday Pack", "Nejvýhodnější balíček HERO", "Trička, boxerky i ponožky",
           "https://heroclothing.cz/products/black-friday-pack"),
        sl("Trička až -60 %", "Custom 10 pack se slevou 60 %", "Vyberte si barvy a velikosti",
           "https://heroclothing.cz/collections/t-shirts-fb-collection"),
        sl("Boxerky až 8+7 zdarma", "Kupte více, ušetříte více", "Pohodlné boxerky HERO",
           "https://heroclothing.cz/collections/hero-boxer-briefs"),
    ],
    "promotions": [
        promo("Pánské basics", "cs", "https://heroclothing.cz/collections/sale"),
    ],
}

HERO_SK = {
    "sitelinks": [
        sl("Black Friday výpredaj", "Zľavy až 60 % na celý e-shop", "Len do 30. 11. – nakúpte teraz",
           "https://heroclothing.sk/collections/sale"),
        sl("Black Friday Pack", "Najvýhodnejší balík HERO", "Tričká, boxerky aj ponožky",
           "https://heroclothing.sk/products/black-friday-pack"),
        sl("Tričká až -60 %", "Custom 10 pack so zľavou 60 %", "Vyberte si farby a veľkosti",
           "https://heroclothing.sk/collections/vsetky-tricka"),
        sl("Boxerky až 8+7 zadarmo", "Kúpte viac, ušetríte viac", "Pohodlné boxerky HERO",
           "https://heroclothing.sk/collections/boxerky"),
    ],
    "promotions": [
        promo("Pánske basics", "sk", "https://heroclothing.sk/collections/sale"),
    ],
}

HERO_PL = {
    "sitelinks": [
        sl("Black Friday wyprzedaż", "Rabaty do 60% na cały sklep", "Tylko do 30.11 – kup teraz",
           "https://heroclothing.pl/collections/sale"),
        sl("Black Friday Pack", "Najkorzystniejszy zestaw HERO", "Koszulki, bokserki i skarpety",
           "https://heroclothing.pl/products/black-friday-pack"),
        sl("Koszulki do -60%", "Zestawy koszulek taniej", "Wybierz kolory i rozmiary",
           "https://heroclothing.pl/collections/hero-t-shirts"),
        sl("Bokserki 8+7 gratis", "Kup więcej, zaoszczędź więcej", "Wygodne bokserki HERO",
           "https://heroclothing.pl/collections/hero-boxer-briefs"),
    ],
    "promotions": [
        promo("Męskie basics", "pl", "https://heroclothing.pl/collections/sale"),
    ],
}


# ----------------------------------------------------------------------------
# Builders
# ----------------------------------------------------------------------------

def build_sitelink_op(client, data):
    op = client.get_type("AssetOperation")
    a = op.create
    a.sitelink_asset.link_text = data["title"]
    a.sitelink_asset.description1 = data["description1"]
    a.sitelink_asset.description2 = data["description2"]
    a.sitelink_asset.start_date = START_DATE
    a.sitelink_asset.end_date = END_DATE
    a.final_urls.append(data["final_url"])
    return op


def build_promotion_op(client, data):
    op = client.get_type("AssetOperation")
    a = op.create
    pa = a.promotion_asset
    pa.promotion_target = data["target"]
    pa.discount_modifier = getattr(
        client.enums.PromotionExtensionDiscountModifierEnum, data["discount_modifier"]
    )
    # Google Ads percent_off: 10_000 = 1% (verified empirically against v24 API).
    pa.percent_off = int(data["percent_off"] * 10_000)
    pa.occasion = getattr(client.enums.PromotionExtensionOccasionEnum, data["occasion"])
    pa.language_code = data["language"]
    pa.start_date = START_DATE
    pa.end_date = END_DATE
    a.final_urls.append(data["final_url"])
    return op


# ----------------------------------------------------------------------------
# Lookups
# ----------------------------------------------------------------------------

def lookup_campaign_rn(client, cid, campaign_name):
    ga = client.get_service("GoogleAdsService")
    escaped = campaign_name.replace("\\", "\\\\").replace("'", "\\'")
    q = (f"SELECT campaign.id, campaign.resource_name FROM campaign "
         f"WHERE campaign.name = '{escaped}'")
    for batch in ga.search_stream(customer_id=cid, query=q):
        for row in batch.results:
            return row.campaign.resource_name
    return None


def fetch_existing(client, cid):
    """Return existing assets keyed for matching:
      {"sitelink": {link_text_lower: rn},
       "promotion": {(target_lower, language_lower): rn}}
    """
    ga = client.get_service("GoogleAdsService")
    out = {"sitelink": {}, "promotion": {}}

    try:
        q = ("SELECT asset.resource_name, asset.sitelink_asset.link_text "
             "FROM asset WHERE asset.type = 'SITELINK'")
        for batch in ga.search_stream(customer_id=cid, query=q):
            for row in batch.results:
                txt = row.asset.sitelink_asset.link_text
                if txt:
                    out["sitelink"][txt.lower()] = row.asset.resource_name
    except Exception as e:
        print(f"  WARNING: sitelink fetch failed — {e}", file=sys.stderr)

    try:
        q = ("SELECT asset.resource_name, asset.promotion_asset.promotion_target, "
             "asset.promotion_asset.language_code FROM asset WHERE asset.type = 'PROMOTION'")
        for batch in ga.search_stream(customer_id=cid, query=q):
            for row in batch.results:
                tgt = row.asset.promotion_asset.promotion_target
                lang = row.asset.promotion_asset.language_code
                if tgt:
                    out["promotion"][(tgt.lower(), lang.lower())] = row.asset.resource_name
    except Exception as e:
        print(f"  WARNING: promotion fetch failed — {e}", file=sys.stderr)

    return out


def existing_customer_links(client, cid):
    ga = client.get_service("GoogleAdsService")
    q = ("SELECT customer_asset.asset, customer_asset.field_type FROM customer_asset "
         "WHERE customer_asset.field_type IN ('SITELINK','PROMOTION')")
    linked = set()
    for r in ga.search(customer_id=cid, query=q):
        linked.add(r.customer_asset.asset)
    return linked


def existing_campaign_links(client, cid, campaign_rn):
    ga = client.get_service("GoogleAdsService")
    escaped = campaign_rn.replace("'", "\\'")
    q = (f"SELECT campaign_asset.asset, campaign_asset.field_type FROM campaign_asset "
         f"WHERE campaign_asset.campaign = '{escaped}' "
         f"AND campaign_asset.field_type IN ('SITELINK','PROMOTION')")
    linked = set()
    for r in ga.search(customer_id=cid, query=q):
        linked.add(r.campaign_asset.asset)
    return linked


# ----------------------------------------------------------------------------
# Mutate helpers
# ----------------------------------------------------------------------------

def push_assets(client, cid, ops, labels):
    """Create assets, return parallel list of resource_names (None on failure)."""
    if not ops:
        return []
    asset_svc = client.get_service("AssetService")
    try:
        req = client.get_type("MutateAssetsRequest")
        req.customer_id = cid
        req.operations.extend(ops)
        req.partial_failure = True
        response = asset_svc.mutate_assets(request=req)
    except Exception as e:
        print(f"    x asset batch failed — {e}")
        return [None] * len(ops)

    failed = _parse_partial_failures(response, ops)
    rns = []
    for i, result in enumerate(response.results):
        if i in failed or not result.resource_name:
            print(f"    x create {labels[i]}")
            rns.append(None)
        else:
            print(f"    + create {labels[i]}")
            rns.append(result.resource_name)
    return rns


def reconcile(client, cid, items, existing_map, key_fn, builder, label_fn):
    """Reuse any matching existing asset, else create."""
    rns = [None] * len(items)
    new_ops, new_idx, new_labels = [], [], []
    reused = 0
    for i, item in enumerate(items):
        key = key_fn(item)
        if key in existing_map:
            rns[i] = existing_map[key]
            print(f"    o reuse  {label_fn(item)}")
            reused += 1
        else:
            new_ops.append(builder(client, item))
            new_idx.append(i)
            new_labels.append(label_fn(item))
    new_rns = push_assets(client, cid, new_ops, new_labels) if new_ops else []
    created = failed = 0
    for j, rn in enumerate(new_rns):
        rns[new_idx[j]] = rn
        if rn:
            created += 1
        else:
            failed += 1
    return rns, reused, created, failed


def link_customer_assets(client, cid, rns, field_type_str, labels, already_linked):
    svc = client.get_service("CustomerAssetService")
    field_type = getattr(client.enums.AssetFieldTypeEnum, field_type_str)
    ops, op_idx = [], []
    for i, rn in enumerate(rns):
        if rn is None:
            continue
        if rn in already_linked:
            print(f"    - already linked at account: {labels[i]}")
            continue
        op = client.get_type("CustomerAssetOperation")
        op.create.asset = rn
        op.create.field_type = field_type
        ops.append(op)
        op_idx.append(i)
    if not ops:
        return 0, 0
    try:
        req = client.get_type("MutateCustomerAssetsRequest")
        req.customer_id = cid
        req.operations.extend(ops)
        req.partial_failure = True
        response = svc.mutate_customer_assets(request=req)
    except Exception as e:
        print(f"    x customer-link batch failed — {e}")
        return 0, len(ops)
    failed = _parse_partial_failures(response, ops)
    linked = link_failed = 0
    for j, _ in enumerate(response.results):
        if j in failed:
            print(f"    x account-link {labels[op_idx[j]]}")
            link_failed += 1
        else:
            print(f"    + account-link {labels[op_idx[j]]}")
            linked += 1
    return linked, link_failed


def link_campaign_assets(client, cid, campaign_rn, rns, field_type_str, labels, already_linked):
    svc = client.get_service("CampaignAssetService")
    field_type = getattr(client.enums.AssetFieldTypeEnum, field_type_str)
    ops, op_idx = [], []
    for i, rn in enumerate(rns):
        if rn is None:
            continue
        if rn in already_linked:
            print(f"    - already linked on campaign: {labels[i]}")
            continue
        op = client.get_type("CampaignAssetOperation")
        op.create.campaign = campaign_rn
        op.create.asset = rn
        op.create.field_type = field_type
        ops.append(op)
        op_idx.append(i)
    if not ops:
        return 0, 0
    try:
        req = client.get_type("MutateCampaignAssetsRequest")
        req.customer_id = cid
        req.operations.extend(ops)
        req.partial_failure = True
        response = svc.mutate_campaign_assets(request=req)
    except Exception as e:
        print(f"    x campaign-link batch failed — {e}")
        return 0, len(ops)
    failed = _parse_partial_failures(response, ops)
    linked = link_failed = 0
    for j, _ in enumerate(response.results):
        if j in failed:
            print(f"    x campaign-link {labels[op_idx[j]]}")
            link_failed += 1
        else:
            print(f"    + campaign-link {labels[op_idx[j]]}")
            linked += 1
    return linked, link_failed


# ----------------------------------------------------------------------------
# Per-account runners
# ----------------------------------------------------------------------------

def run_account_level(client, cid, name, bundle):
    print(f"\n=== {name} ({cid}) — account level ===")
    existing = fetch_existing(client, cid)
    already_linked = existing_customer_links(client, cid)

    print(f"  Existing in account: {len(existing['sitelink'])} sitelinks, "
          f"{len(existing['promotion'])} promotions "
          f"({len(already_linked)} already account-linked)")

    # --- Sitelinks ---
    print("  Sitelinks:")
    sl_items = bundle["sitelinks"]
    sl_labels = [f"{s['title']} → {s['final_url']}" for s in sl_items]
    sl_rns, sl_r, sl_c, sl_f = reconcile(
        client, cid, sl_items, existing["sitelink"],
        key_fn=lambda s: s["title"].lower(),
        builder=build_sitelink_op,
        label_fn=lambda s: f"{s['title']} → {s['final_url']}",
    )
    sl_linked, sl_lf = link_customer_assets(client, cid, sl_rns, "SITELINK", sl_labels, already_linked)

    # --- Promotions ---
    print("  Promotions:")
    pr_items = bundle["promotions"]
    pr_labels = [f"{p['target']} ({p['language']}) → {p['final_url']}" for p in pr_items]
    pr_rns, pr_r, pr_c, pr_f = reconcile(
        client, cid, pr_items, existing["promotion"],
        key_fn=lambda p: (p["target"].lower(), p["language"].lower()),
        builder=build_promotion_op,
        label_fn=lambda p: f"{p['target']} ({p['language']}) → {p['final_url']}",
    )
    pr_linked, pr_lf = link_customer_assets(client, cid, pr_rns, "PROMOTION", pr_labels, already_linked)

    return {
        "name": name, "cid": cid,
        "sitelinks": (sl_c, sl_r, sl_f, sl_linked, sl_lf),
        "promotions": (pr_c, pr_r, pr_f, pr_linked, pr_lf),
    }


def run_campaign_level(client, cid, name, campaigns):
    print(f"\n=== {name} ({cid}) — campaign level ===")
    existing = fetch_existing(client, cid)
    print(f"  Existing in account: {len(existing['sitelink'])} sitelinks, "
          f"{len(existing['promotion'])} promotions")

    out = {"name": name, "cid": cid, "per_campaign": []}

    for campaign_name, bundle in campaigns.items():
        print(f"\n  Campaign: {campaign_name}")
        campaign_rn = lookup_campaign_rn(client, cid, campaign_name)
        if not campaign_rn:
            print(f"    x campaign not found — skipping")
            out["per_campaign"].append((campaign_name, None))
            continue
        already_linked = existing_campaign_links(client, cid, campaign_rn)
        print(f"    (campaign already has {len(already_linked)} SITELINK/PROMOTION links)")

        # Sitelinks
        sl_items = bundle["sitelinks"]
        sl_labels = [f"{s['title']} → {s['final_url']}" for s in sl_items]
        sl_rns, sl_r, sl_c, sl_f = reconcile(
            client, cid, sl_items, existing["sitelink"],
            key_fn=lambda s: s["title"].lower(),
            builder=build_sitelink_op,
            label_fn=lambda s: f"{s['title']} → {s['final_url']}",
        )
        sl_linked, sl_lf = link_campaign_assets(
            client, cid, campaign_rn, sl_rns, "SITELINK", sl_labels, already_linked
        )

        # Promotions
        pr_items = bundle["promotions"]
        pr_labels = [f"{p['target']} ({p['language']}) → {p['final_url']}" for p in pr_items]
        pr_rns, pr_r, pr_c, pr_f = reconcile(
            client, cid, pr_items, existing["promotion"],
            key_fn=lambda p: (p["target"].lower(), p["language"].lower()),
            builder=build_promotion_op,
            label_fn=lambda p: f"{p['target']} ({p['language']}) → {p['final_url']}",
        )
        pr_linked, pr_lf = link_campaign_assets(
            client, cid, campaign_rn, pr_rns, "PROMOTION", pr_labels, already_linked
        )

        out["per_campaign"].append((campaign_name, {
            "sitelinks": (sl_c, sl_r, sl_f, sl_linked, sl_lf),
            "promotions": (pr_c, pr_r, pr_f, pr_linked, pr_lf),
        }))

        # Refresh the existing-assets cache with newly created resource_names so
        # the next campaign in the same account can reuse them.
        for i, rn in enumerate(sl_rns):
            if rn:
                existing["sitelink"][sl_items[i]["title"].lower()] = rn
        for i, rn in enumerate(pr_rns):
            if rn:
                existing["promotion"][(pr_items[i]["target"].lower(), pr_items[i]["language"].lower())] = rn

    return out


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    client = init_google_ads_client()

    results = []
    # Account-level pushes
    results.append(run_account_level(client, "5753392380", "HERO CZ", HERO_CZ))
    results.append(run_account_level(client, "8145516592", "HERO SK", HERO_SK))
    results.append(run_account_level(client, "6718552884", "HERO PL", HERO_PL))
    # Campaign-level push for HERO EU
    results.append(run_campaign_level(client, "5007494125", "HERO EU", HERO_EU_CAMPAIGNS))

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for r in results:
        if "per_campaign" in r:
            print(f"\n{r['name']} ({r['cid']}) — campaign level")
            for cname, stats in r["per_campaign"]:
                if stats is None:
                    print(f"  {cname}: CAMPAIGN NOT FOUND")
                    continue
                sc, sr, sf, sl_l, sl_lf = stats["sitelinks"]
                pc, pr_, pf, pl_, plf = stats["promotions"]
                print(f"  {cname}:")
                print(f"    sitelinks:  create {sc} / reuse {sr} / create-fail {sf}; "
                      f"linked {sl_l} ({sl_lf} link-fail)")
                print(f"    promotions: create {pc} / reuse {pr_} / create-fail {pf}; "
                      f"linked {pl_} ({plf} link-fail)")
        else:
            sc, sr, sf, sl_l, sl_lf = r["sitelinks"]
            pc, pr_, pf, pl_, plf = r["promotions"]
            print(f"\n{r['name']} ({r['cid']}) — account level")
            print(f"  sitelinks:  create {sc} / reuse {sr} / create-fail {sf}; "
                  f"linked {sl_l} ({sl_lf} link-fail)")
            print(f"  promotions: create {pc} / reuse {pr_} / create-fail {pf}; "
                  f"linked {pl_} ({plf} link-fail)")

    print(f"\nSchedule on every asset: {START_DATE} → {END_DATE}")


if __name__ == "__main__":
    main()
