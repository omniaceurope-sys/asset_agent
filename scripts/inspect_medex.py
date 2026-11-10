"""Inspect sitelinks + promotions on all 4 Medex accounts — print text, URL, dates."""
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

TITLES_SL = {
    "Črni teden vitalnosti", "Črni teden imunosti", "Črni teden aktivnosti", "Črni petek",
    "Crni tjedan vitalnosti", "Crni tjedan imuniteta", "Crni tjedan aktivnosti",
    "Černý týden vitality", "Černý týden imunity", "Černý týden aktivity",
    "Čierny týždeň vitality", "Čierny týždeň imunity", "Čierny týždeň aktivity",
    "Black Friday",
}

TARGETS = {
    "izdelki za vitalnost", "matični mleček", "izdelki za aktivnost", "medex izdelki",
    "proizvodi vitalnosti", "matična mliječ", "proizvodi aktivnosti", "medex proizvodi",
    "produkty vitality", "mateří kašička", "produkty aktivity", "produkty medex",
    "materská kašička",
}


def main():
    client = init_google_ads_client()
    ga = client.get_service("GoogleAdsService")

    for cid, name in ACCOUNTS:
        print(f"\n=== {name} ({cid}) ===")

        print("  SITELINKS matching our set:")
        q = ("SELECT asset.id, asset.sitelink_asset.link_text, "
             "asset.sitelink_asset.description1, asset.sitelink_asset.description2, "
             "asset.sitelink_asset.start_date, asset.sitelink_asset.end_date, "
             "asset.final_urls "
             "FROM asset WHERE asset.type = 'SITELINK'")
        try:
            for r in ga.search(customer_id=cid, query=q):
                sa = r.asset.sitelink_asset
                if sa.link_text in TITLES_SL:
                    urls = list(r.asset.final_urls)
                    print(f"    [{r.asset.id}] '{sa.link_text}' | "
                          f"{sa.description1} | {sa.description2}")
                    print(f"       dates: {sa.start_date or '(none)'} → "
                          f"{sa.end_date or '(none)'}  url: {urls}")
        except Exception as e:
            print(f"    ERROR: {e}")

        print("  PROMOTIONS matching our set:")
        q = ("SELECT asset.id, asset.promotion_asset.promotion_target, "
             "asset.promotion_asset.percent_off, asset.promotion_asset.start_date, "
             "asset.promotion_asset.end_date, asset.promotion_asset.language_code, "
             "asset.final_urls "
             "FROM asset WHERE asset.type = 'PROMOTION'")
        try:
            for r in ga.search(customer_id=cid, query=q):
                pa = r.asset.promotion_asset
                if pa.promotion_target.lower() in TARGETS:
                    urls = list(r.asset.final_urls)
                    pct = pa.percent_off / 10_000  # micros → %
                    print(f"    [{r.asset.id}] '{pa.promotion_target}' @ {pct}% "
                          f"[{pa.language_code}]")
                    print(f"       dates: {pa.start_date or '(none)'} → "
                          f"{pa.end_date or '(none)'}  url: {urls}")
        except Exception as e:
            print(f"    ERROR: {e}")


if __name__ == "__main__":
    main()
