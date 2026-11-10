"""
One-off push script for heroclothing.eu/hr-hr/ → account 500-749-4125 (HERO EU),
campaign-level on |HR|-Search-Brand-[Bid:mClicks-0.08].

For each target asset:
  - if it already exists in the account → reuse its resource_name
  - else → create it via AssetService
Then link every resource_name to the campaign via CampaignAssetService.
"""

import sys
from pathlib import Path

# Force UTF-8 console output (Windows defaults to cp1250 which chokes on ✓ ⊘)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

sys.path.insert(0, str(Path(__file__).parent))

from google_ads_assets import (  # noqa: E402
    init_google_ads_client,
    _build_sitelink_operation,
    _build_callout_operation,
    _build_snippet_operation,
    _parse_partial_failures,
)

CUSTOMER_ID = "5007494125"
ACCOUNT_NAME = "HERO EU"
CAMPAIGN_NAME = "|HR|-Search-Brand-[Bid:mClicks-0.08]"

SITELINKS = [
    {"title": "Bokserice",             "description1": "Mekana udobnost cijeli dan",   "description2": "Setovi 3+1, 6 i 9 komada",       "final_url": "https://heroclothing.eu/hr-hr/collections/boxers"},
    {"title": "Majice kratkih rukava", "description1": "Premium kvaliteta i fit",      "description2": "Setovi 3, 4, 6 i 9 komada",      "final_url": "https://heroclothing.eu/hr-hr/collections/t-shirts"},
    {"title": "Pojasevi",              "description1": "Kvalitetan dodatak outfitu",   "description2": "Klasične i moderne varijante",   "final_url": "https://heroclothing.eu/hr-hr/pages/hero-belts"},
    {"title": "Najprodavanije",        "description1": "Što kupci najviše biraju",     "description2": "Top komadi HERO kolekcije",      "final_url": "https://heroclothing.eu/hr-hr/collections/bestsellers"},
    {"title": "Novi dolasci",          "description1": "Najnoviji komadi u ponudi",    "description2": "Sezonska kolekcija HERO",        "final_url": "https://heroclothing.eu/hr-hr/collections/new-arrivals"},
    {"title": "Prodaja",               "description1": "Top komadi po nižoj cijeni",   "description2": "Dok ima zaliha",                 "final_url": "https://heroclothing.eu/hr-hr/collections/sale"},
]

CALLOUTS = [
    "Besplatna Dostava Od 69€",
    "Ocjena 4,7 Od 5 Zvjezdica",
    "100.000+ Sretnih Kupaca",
    "Udobnost Cijeli Dan",
    "Premium Kvaliteta",
    "Setovi Po Sniženoj Cijeni",
    "Široki Izbor Boja",
    "Sigurna Online Kupnja",
    "Brza Dostava U Hrvatsku",
    "Povrat U 14 Dana",
    "Veličine S Do 3XL",
    "Muška Premium Kolekcija",
]

SNIPPETS = [
    {"header": "Types",     "values": ["Bokserice", "Majice", "Pojasevi", "Setovi 3+1", "Setovi 6 komada", "Setovi 9 komada"]},
    {"header": "Styles",    "values": ["Crna", "Bijela", "Mornarsko plava", "Maslinasto zelena", "Siva", "Tirkizna"]},
    {"header": "Amenities", "values": ["Besplatna dostava", "Setovi sa popustom", "Povrat 14 dana", "Recenzije 4,7/5", "Sigurna kupnja"]},
]


def lookup_campaign(client, customer_id: str, campaign_name: str) -> tuple[str, str]:
    """Find a campaign by exact name. Returns (campaign_id, resource_name)."""
    ga_service = client.get_service("GoogleAdsService")
    escaped = campaign_name.replace("\\", "\\\\").replace("'", "\\'")
    query = f"""
        SELECT campaign.id, campaign.name, campaign.resource_name, campaign.status
        FROM campaign
        WHERE campaign.name = '{escaped}'
    """
    stream = ga_service.search_stream(customer_id=customer_id, query=query)
    for batch in stream:
        for row in batch.results:
            return str(row.campaign.id), row.campaign.resource_name
    sys.exit(f"ERROR: campaign '{campaign_name}' not found in account {customer_id}")


def fetch_existing_resource_names(client, customer_id: str) -> dict:
    """Return dicts mapping lowercased identifier → resource_name for each asset type."""
    ga_service = client.get_service("GoogleAdsService")
    out = {"sitelink": {}, "callout": {}, "snippet": {}}
    queries = [
        ("sitelink",
         "SELECT asset.resource_name, asset.sitelink_asset.link_text "
         "FROM asset WHERE asset.type = 'SITELINK'",
         lambda r: r.asset.sitelink_asset.link_text),
        ("callout",
         "SELECT asset.resource_name, asset.callout_asset.callout_text "
         "FROM asset WHERE asset.type = 'CALLOUT'",
         lambda r: r.asset.callout_asset.callout_text),
        ("snippet",
         "SELECT asset.resource_name, asset.structured_snippet_asset.header "
         "FROM asset WHERE asset.type = 'STRUCTURED_SNIPPET'",
         lambda r: r.asset.structured_snippet_asset.header),
    ]
    for key, query, extractor in queries:
        try:
            stream = ga_service.search_stream(customer_id=customer_id, query=query)
            for batch in stream:
                for row in batch.results:
                    text = extractor(row)
                    if text:
                        out[key][text.lower()] = row.asset.resource_name
        except Exception as e:
            print(f"  WARNING: Could not fetch existing {key}: {e}", file=sys.stderr)
    return out


def push_assets_and_collect_rns(client, customer_id, operations, label_fn):
    """Push asset operations, print per-item status, return list of resource_names."""
    asset_service = client.get_service("AssetService")
    try:
        request = client.get_type("MutateAssetsRequest")
        request.customer_id = customer_id
        request.operations.extend(operations)
        request.partial_failure = True
        response = asset_service.mutate_assets(request=request)
    except Exception as e:
        print(f"  x Batch failed entirely - {e}")
        return [None] * len(operations)

    failed_idx = _parse_partial_failures(response, operations)
    resource_names = []
    for i, result in enumerate(response.results):
        if i in failed_idx or not result.resource_name:
            print(f"  x {label_fn(i)} (API rejected)")
            resource_names.append(None)
        else:
            print(f"  + {label_fn(i)}")
            resource_names.append(result.resource_name)
    return resource_names


def link_at_campaign_level(client, customer_id, campaign_resource_name,
                            resource_names, field_type_str, label_fn):
    """Create CampaignAsset links for each asset resource at campaign level."""
    campaign_asset_service = client.get_service("CampaignAssetService")
    field_type_enum = client.enums.AssetFieldTypeEnum
    field_type = getattr(field_type_enum, field_type_str)

    operations = []
    op_index_to_orig_index = []
    for i, rn in enumerate(resource_names):
        if rn is None:
            continue
        op = client.get_type("CampaignAssetOperation")
        ca = op.create
        ca.campaign = campaign_resource_name
        ca.asset = rn
        ca.field_type = field_type
        operations.append(op)
        op_index_to_orig_index.append(i)

    if not operations:
        return 0, 0

    try:
        request = client.get_type("MutateCampaignAssetsRequest")
        request.customer_id = customer_id
        request.operations.extend(operations)
        request.partial_failure = True
        response = campaign_asset_service.mutate_campaign_assets(request=request)
    except Exception as e:
        print(f"  x Campaign-level link batch failed - {e}")
        return 0, len(operations)

    failed_idx = _parse_partial_failures(response, operations)
    linked = 0
    failed = 0
    for j, _result in enumerate(response.results):
        orig_i = op_index_to_orig_index[j]
        if j in failed_idx:
            print(f"  x link {label_fn(orig_i)}")
            failed += 1
        else:
            print(f"  + link {label_fn(orig_i)}")
            linked += 1
    return linked, failed


def reconcile_and_create(client, customer_id, items, existing_map, key_fn, builder, label_fn):
    """
    For each target asset:
      - if its key is already in existing_map, reuse resource_name (count as 'reused')
      - else create via AssetService and collect new resource_name (count as 'created')
    Returns (resource_names_in_original_order, reused_count, created_count, failed_count).
    """
    resource_names: list[str | None] = [None] * len(items)
    new_indices: list[int] = []
    new_ops = []

    reused = 0
    for i, item in enumerate(items):
        key = key_fn(item).lower()
        if key in existing_map:
            resource_names[i] = existing_map[key]
            print(f"  o {label_fn(item)} (reusing existing asset)")
            reused += 1
        else:
            new_indices.append(i)
            new_ops.append(builder(client, item))

    created = 0
    failed = 0
    if new_ops:
        new_rns = push_assets_and_collect_rns(
            client, customer_id, new_ops,
            lambda j: label_fn(items[new_indices[j]])
        )
        for j, rn in enumerate(new_rns):
            orig_i = new_indices[j]
            resource_names[orig_i] = rn
            if rn:
                created += 1
            else:
                failed += 1
    return resource_names, reused, created, failed


def main():
    print(f"\nAccount: {CUSTOMER_ID} ({ACCOUNT_NAME})")
    client = init_google_ads_client()

    campaign_id, campaign_rn = lookup_campaign(client, CUSTOMER_ID, CAMPAIGN_NAME)
    print(f"Campaign: {CAMPAIGN_NAME} (id {campaign_id})")

    existing = fetch_existing_resource_names(client, CUSTOMER_ID)
    print(f"\nExisting in account: "
          f"{len(existing['sitelink'])} sitelinks, "
          f"{len(existing['callout'])} callouts, "
          f"{len(existing['snippet'])} snippets")

    # --- SITELINKS ---
    print("\nReconciling sitelinks (create new, reuse existing)...")
    sl_rns, sl_reused, sl_created, sl_failed = reconcile_and_create(
        client, CUSTOMER_ID, SITELINKS, existing["sitelink"],
        key_fn=lambda sl: sl["title"],
        builder=_build_sitelink_operation,
        label_fn=lambda sl: f"{sl['title']} -> {sl['final_url']}",
    )
    print("\nLinking sitelinks at campaign level...")
    sl_linked, sl_link_failed = link_at_campaign_level(
        client, CUSTOMER_ID, campaign_rn, sl_rns, "SITELINK",
        lambda i: SITELINKS[i]["title"],
    )

    # --- CALLOUTS ---
    print("\nReconciling callouts (create new, reuse existing)...")
    co_rns, co_reused, co_created, co_failed = reconcile_and_create(
        client, CUSTOMER_ID, CALLOUTS, existing["callout"],
        key_fn=lambda t: t,
        builder=_build_callout_operation,
        label_fn=lambda t: t,
    )
    print("\nLinking callouts at campaign level...")
    co_linked, co_link_failed = link_at_campaign_level(
        client, CUSTOMER_ID, campaign_rn, co_rns, "CALLOUT",
        lambda i: CALLOUTS[i],
    )

    # --- STRUCTURED SNIPPETS ---
    # NOTE: we match by header alone (Google Ads quirk: one snippet per header per
    # account is typical). If the existing snippet has different values, we still
    # reuse it rather than create a duplicate.
    print("\nReconciling structured snippets (create new, reuse existing)...")
    sn_rns, sn_reused, sn_created, sn_failed = reconcile_and_create(
        client, CUSTOMER_ID, SNIPPETS, existing["snippet"],
        key_fn=lambda s: s["header"],
        builder=_build_snippet_operation,
        label_fn=lambda s: f"{s['header']}: {', '.join(s['values'])}",
    )
    print("\nLinking structured snippets at campaign level...")
    sn_linked, sn_link_failed = link_at_campaign_level(
        client, CUSTOMER_ID, campaign_rn, sn_rns, "STRUCTURED_SNIPPET",
        lambda i: SNIPPETS[i]["header"],
    )

    # --- SUMMARY ---
    print("\n" + "=" * 60)
    print(f"SUMMARY  -  Account {CUSTOMER_ID} ({ACCOUNT_NAME})")
    print(f"Campaign: {CAMPAIGN_NAME}")
    print(f"  Sitelinks:  {sl_created} created, {sl_reused} reused, {sl_failed} create-fail; "
          f"linked: {sl_linked} ({sl_link_failed} link failures)")
    print(f"  Callouts:   {co_created} created, {co_reused} reused, {co_failed} create-fail; "
          f"linked: {co_linked} ({co_link_failed} link failures)")
    print(f"  Snippets:   {sn_created} created, {sn_reused} reused, {sn_failed} create-fail; "
          f"linked: {sn_linked} ({sn_link_failed} link failures)")
    print(f"  Total assets created:        {sl_created + co_created + sn_created}")
    print(f"  Total campaign-level links:  {sl_linked + co_linked + sn_linked}")
    print("=" * 60)


if __name__ == "__main__":
    main()
