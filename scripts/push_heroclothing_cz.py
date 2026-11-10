"""
One-off push script for heroclothing.cz → account 575-339-2380.

Pre-approved Czech assets are defined inline. Creates each asset via
AssetService, then links it to the customer at account level via
CustomerAssetService with the correct asset_field_type.
"""

import sys
from pathlib import Path

# Make sibling module importable
sys.path.insert(0, str(Path(__file__).parent))

from google_ads_assets import (  # noqa: E402
    init_google_ads_client,
    fetch_existing_assets,
    _build_sitelink_operation,
    _build_callout_operation,
    _build_snippet_operation,
    _parse_partial_failures,
)

CUSTOMER_ID = "5753392380"
ACCOUNT_NAME = "heroclothing.cz"

SITELINKS = [
    {"title": "Pánská trička",     "description1": "Pohodlné střihy a kvalita",     "description2": "Multi-packy za skvělé ceny",   "final_url": "https://heroclothing.cz/collections/hero-clothing"},
    {"title": "Pánské boxerky",    "description1": "Měkký materiál, perfektní fit",  "description2": "Balíčky 3, 4, 6 nebo 9 ks",    "final_url": "https://heroclothing.cz/collections/hero-boxer-briefs"},
    {"title": "Pánské ponožky",    "description1": "Kvalitní materiál, drží tvar",   "description2": "Výhodné multi-packy",           "final_url": "https://heroclothing.cz/collections/hero-socks"},
    {"title": "Dlouhé rukávy",     "description1": "Pohodlné kousky na chladné dny", "description2": "Premium kvalita, férové ceny",  "final_url": "https://heroclothing.cz/collections/long-sleeve"},
    {"title": "Pánské opasky",     "description1": "Doplňky k pánským outfitům",     "description2": "Kvalitní zpracování",           "final_url": "https://heroclothing.cz/pages/hero-belts"},
    {"title": "Bestsellery",       "description1": "Co nakupují ostatní nejvíc",     "description2": "Vybráno z 85 000 objednávek",   "final_url": "https://heroclothing.cz/collections/bestsellery"},
    {"title": "Novinky",           "description1": "Nově přidané kousky",            "description2": "Sleduj, co máme aktuálně",      "final_url": "https://heroclothing.cz/collections/novinky"},
    {"title": "Výprodej",          "description1": "Naše top kousky se slevou",      "description2": "Dokud zásoby stačí",            "final_url": "https://heroclothing.cz/collections/sale"},
    {"title": "Custom Packs",      "description1": "Sestav si vlastní balíček",      "description2": "Ušetři při větším nákupu",      "final_url": "https://heroclothing.cz/collections/custom-packs"},
    {"title": "Recenze zákazníků", "description1": "3 500+ hodnocení, 88 % 5 hvězd", "description2": "Přečti si, co píší zákazníci", "final_url": "https://heroclothing.cz/pages/spokojenych-zakazniku"},
    {"title": "Dárkové karty",     "description1": "Skvělý tip na dárek",            "description2": "Doruč e-mailem v pár minutách", "final_url": "https://heroclothing.cz/products/darkova-karta-hero"},
    {"title": "Finální výprodej",  "description1": "Poslední kusy za nejnižší ceny", "description2": "Bez možnosti vrácení zboží",    "final_url": "https://heroclothing.cz/collections/finalni-vyprodej"},
]

CALLOUTS = [
    "Doprava zdarma od 1700 Kč",
    "14 dní na vrácení zboží",
    "Přes 85 000 zákazníků",
    "Hodnocení 4,8 z 5 hvězd",
    "Pohodlné pánské oblečení",
    "Multi-packy se slevou",
    "Kvalitní materiál",
    "Skvělý poměr cena/kvalita",
    "Bezpečný online nákup",
    "Více než 3 500 recenzí",
    "Možnost dárkové karty",
    "Snadné objednání online",
]

SNIPPETS = [
    {"header": "Types",     "values": ["Trička", "Boxerky", "Ponožky", "Mikiny", "Dlouhé rukávy", "Opasky", "Multi-packy"]},
    {"header": "Amenities", "values": ["Doprava zdarma", "Multi-packy", "Dárkové karty", "Vrácení 14 dní", "Recenze 4,8/5"]},
]


def push_assets_and_collect_rns(client, customer_id, operations, label_fn):
    """Push a batch of asset operations, print ✓/✗ per item, return list of
    resource_names for the successfully created ones (in original order, None for failures)."""
    asset_service = client.get_service("AssetService")
    try:
        request = client.get_type("MutateAssetsRequest")
        request.customer_id = customer_id
        request.operations.extend(operations)
        request.partial_failure = True
        response = asset_service.mutate_assets(request=request)
    except Exception as e:
        print(f"  ✗ Batch failed entirely — {e}")
        return [None] * len(operations)

    failed_idx = _parse_partial_failures(response, operations)
    resource_names = []
    for i, result in enumerate(response.results):
        if i in failed_idx or not result.resource_name:
            print(f"  ✗ {label_fn(i)} (API rejected)")
            resource_names.append(None)
        else:
            print(f"  ✓ {label_fn(i)}")
            resource_names.append(result.resource_name)
    return resource_names


def link_at_account_level(client, customer_id, resource_names, field_type_str, label_fn):
    """Create CustomerAsset links for each asset resource at account level."""
    customer_asset_service = client.get_service("CustomerAssetService")
    field_type_enum = client.enums.AssetFieldTypeEnum
    field_type = getattr(field_type_enum, field_type_str)

    operations = []
    op_index_to_orig_index = []
    for i, rn in enumerate(resource_names):
        if rn is None:
            continue
        op = client.get_type("CustomerAssetOperation")
        ca = op.create
        ca.asset = rn
        ca.field_type = field_type
        operations.append(op)
        op_index_to_orig_index.append(i)

    if not operations:
        return 0, 0

    try:
        request = client.get_type("MutateCustomerAssetsRequest")
        request.customer_id = customer_id
        request.operations.extend(operations)
        request.partial_failure = True
        response = customer_asset_service.mutate_customer_assets(request=request)
    except Exception as e:
        print(f"  ✗ Account-level link batch failed — {e}")
        return 0, len(operations)

    failed_idx = _parse_partial_failures(response, operations)
    linked = 0
    failed = 0
    for j, _result in enumerate(response.results):
        orig_i = op_index_to_orig_index[j]
        if j in failed_idx:
            print(f"  ✗ link {label_fn(orig_i)}")
            failed += 1
        else:
            print(f"  ✓ link {label_fn(orig_i)}")
            linked += 1
    return linked, failed


def main():
    print(f"\nAccount: {CUSTOMER_ID} ({ACCOUNT_NAME})")
    client = init_google_ads_client()
    existing = fetch_existing_assets(client, CUSTOMER_ID)

    # --- SITELINKS ---
    print("\nCreating sitelinks...")
    sl_to_push = []
    sl_skipped_labels = []
    for sl in SITELINKS:
        if sl["title"].lower() in existing["sitelink_titles"]:
            print(f"  ⊘ {sl['title']} (already exists)")
            sl_skipped_labels.append(sl["title"])
        else:
            sl_to_push.append(sl)
    sl_ops = [_build_sitelink_operation(client, sl) for sl in sl_to_push]
    sl_rns = push_assets_and_collect_rns(
        client, CUSTOMER_ID, sl_ops,
        lambda i: f"{sl_to_push[i]['title']} → {sl_to_push[i]['final_url']}"
    ) if sl_ops else []

    print("\nLinking sitelinks at account level...")
    sl_linked, sl_link_failed = link_at_account_level(
        client, CUSTOMER_ID, sl_rns, "SITELINK",
        lambda i: sl_to_push[i]["title"]
    ) if sl_rns else (0, 0)

    # --- CALLOUTS ---
    print("\nCreating callouts...")
    co_to_push = []
    co_skipped = []
    for text in CALLOUTS:
        if text.lower() in existing["callout_texts"]:
            print(f"  ⊘ {text} (already exists)")
            co_skipped.append(text)
        else:
            co_to_push.append(text)
    co_ops = [_build_callout_operation(client, t) for t in co_to_push]
    co_rns = push_assets_and_collect_rns(
        client, CUSTOMER_ID, co_ops,
        lambda i: co_to_push[i]
    ) if co_ops else []

    print("\nLinking callouts at account level...")
    co_linked, co_link_failed = link_at_account_level(
        client, CUSTOMER_ID, co_rns, "CALLOUT",
        lambda i: co_to_push[i]
    ) if co_rns else (0, 0)

    # --- STRUCTURED SNIPPETS ---
    print("\nCreating structured snippets...")
    sn_to_push = []
    sn_skipped = []
    for snippet in SNIPPETS:
        if snippet["header"].lower() in existing["snippet_headers"]:
            print(f"  ⊘ {snippet['header']} (already exists)")
            sn_skipped.append(snippet["header"])
        else:
            sn_to_push.append(snippet)
    sn_ops = [_build_snippet_operation(client, s) for s in sn_to_push]
    sn_rns = push_assets_and_collect_rns(
        client, CUSTOMER_ID, sn_ops,
        lambda i: f"{sn_to_push[i]['header']}: {', '.join(sn_to_push[i]['values'])}"
    ) if sn_ops else []

    print("\nLinking structured snippets at account level...")
    sn_linked, sn_link_failed = link_at_account_level(
        client, CUSTOMER_ID, sn_rns, "STRUCTURED_SNIPPET",
        lambda i: sn_to_push[i]["header"]
    ) if sn_rns else (0, 0)

    # --- SUMMARY ---
    sl_created = sum(1 for r in sl_rns if r)
    co_created = sum(1 for r in co_rns if r)
    sn_created = sum(1 for r in sn_rns if r)
    print("\n" + "=" * 60)
    print(f"SUMMARY  —  Account {CUSTOMER_ID} ({ACCOUNT_NAME})")
    print(f"  Sitelinks:  {sl_created} created, {len(sl_skipped_labels)} skipped, "
          f"linked at account level: {sl_linked} ({sl_link_failed} link failures)")
    print(f"  Callouts:   {co_created} created, {len(co_skipped)} skipped, "
          f"linked at account level: {co_linked} ({co_link_failed} link failures)")
    print(f"  Snippets:   {sn_created} created, {len(sn_skipped)} skipped, "
          f"linked at account level: {sn_linked} ({sn_link_failed} link failures)")
    print(f"  Total assets created: {sl_created + co_created + sn_created}")
    print(f"  Total account-level links: {sl_linked + co_linked + sn_linked}")
    print("=" * 60)


if __name__ == "__main__":
    main()
