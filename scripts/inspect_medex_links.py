"""Check which Medex sitelinks/promos are linked at account level."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from google_ads_assets import init_google_ads_client  # noqa: E402

ACCOUNTS = [
    ("6465487333", "Medex SI"),
    ("4873324748", "Medex HR"),
    ("5342656678", "Medex CZ"),
    ("8860201997", "Medex SK"),
]

# Our target asset IDs from the inspect run — rebuild them per account.
EXPECTED = {
    "6465487333": {
        "sitelinks": {
            "Črni teden vitalnosti": "434354160377",
            "Črni teden imunosti": "434459407789",
            "Črni teden aktivnosti": "434539273611",
            "Črni petek": "434354141186",
        },
        "promos": {
            "Izdelki za vitalnost": "434539462743",
            "Matični mleček": "434459759977",
            "Izdelki za aktivnost": "434539887402",
            "Medex izdelki": "434460323479",
        },
    },
    "4873324748": {
        "sitelinks": {
            "Crni tjedan vitalnosti": "434459460007",
            "Crni tjedan imuniteta": "434539291317",
            "Crni tjedan aktivnosti": "434539290366",
            "Black Friday": "434459460019",
        },
        "promos": {
            "Proizvodi vitalnosti": "434355211004",
            "Matična mliječ": "434540579598",
            "Proizvodi aktivnosti": "434540732136",
            "Medex proizvodi": "434540682438",
        },
    },
    "5342656678": {
        "sitelinks": {
            "Černý týden vitality": "434539294413",
            "Černý týden imunity": "434459462449",
            "Černý týden aktivity": "434539291725",
            "Black Friday": "434354167658",
        },
        "promos": {
            "Produkty vitality": "434355909740",
            "Mateří kašička": "434461458724",
            "Produkty aktivity": "434541327216",
            "Produkty Medex": "434356281989",
        },
    },
    "8860201997": {
        "sitelinks": {
            "Čierny týždeň vitality": "434354168273",
            "Čierny týždeň imunity": "434539294845",
            "Čierny týždeň aktivity": "434539292127",
            "Black Friday": "434354168276",
        },
        "promos": {
            "Produkty vitality": "434541564663",
            "Materská kašička": "434356510070",
            "Produkty aktivity": "434357051147",
            "Produkty Medex": "434357423843",
        },
    },
}


def main():
    client = init_google_ads_client()
    ga = client.get_service("GoogleAdsService")

    for cid, name in ACCOUNTS:
        print(f"\n=== {name} ({cid}) — account-level links ===")
        q = ("SELECT customer_asset.asset, customer_asset.field_type, "
             "customer_asset.status FROM customer_asset "
             "WHERE customer_asset.field_type IN ('SITELINK','PROMOTION')")
        linked = {}
        try:
            for r in ga.search(customer_id=cid, query=q):
                ca = r.customer_asset
                asset_id = ca.asset.rsplit("/", 1)[-1]
                linked[asset_id] = (ca.field_type.name, ca.status.name)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        for title, asset_id in EXPECTED[cid]["sitelinks"].items():
            info = linked.get(asset_id)
            tag = f"{info[0]} {info[1]}" if info else "NOT LINKED"
            print(f"  SITELINK  {asset_id} '{title}' → {tag}")
        for target, asset_id in EXPECTED[cid]["promos"].items():
            info = linked.get(asset_id)
            tag = f"{info[0]} {info[1]}" if info else "NOT LINKED"
            print(f"  PROMOTION {asset_id} '{target}' → {tag}")


if __name__ == "__main__":
    main()
