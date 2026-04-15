"""
streamlit_app.py — Google Ads Asset Builder UI

Deployable to Streamlit Cloud (streamlit.io).
Credentials are loaded from st.secrets (set in the Streamlit Cloud dashboard
or locally in .streamlit/secrets.toml).

Local run:
    streamlit run streamlit_app.py
"""

import os
import sys
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# Path setup — make scripts/ importable
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent / "scripts"))

# ---------------------------------------------------------------------------
# Page configuration (must be first Streamlit call)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Google Ads Asset Builder",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

def _get_anthropic_key() -> str | None:
    """Return Anthropic API key from secrets or environment."""
    try:
        return st.secrets["ANTHROPIC_API_KEY"]
    except (KeyError, FileNotFoundError):
        return os.environ.get("ANTHROPIC_API_KEY")


def _get_google_ads_creds() -> dict | None:
    """Return Google Ads credentials dict from secrets or local config file."""
    try:
        creds = dict(st.secrets["google_ads"])
        if str(creds.get("developer_token", "")).startswith("X"):
            return None
        return creds
    except (KeyError, FileNotFoundError):
        pass

    config_path = Path(__file__).parent / "config" / "google_ads.yaml"
    if config_path.exists():
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            creds = yaml.safe_load(f)
        if creds and not str(creds.get("developer_token", "X")).startswith("X"):
            return creds
    return None


def _get_accounts() -> dict:
    """
    Return {account_id: name} from secrets or config file.
    Used as a fallback when Ads credentials are not configured.
    """
    try:
        raw = dict(st.secrets.get("accounts", {}))
        return {k: (v if isinstance(v, str) else v.get("name", k)) for k, v in raw.items()}
    except (KeyError, FileNotFoundError, AttributeError):
        pass

    config_path = Path(__file__).parent / "config" / "accounts.yaml"
    if config_path.exists():
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        accounts = (data or {}).get("accounts", {})
        return {k: v.get("name", k) if isinstance(v, dict) else v
                for k, v in accounts.items()}
    return {}


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _char_label(text: str, limit: int) -> str:
    """Return a colored markdown character-count badge."""
    n = len(text)
    if n > limit:
        return f":red[🔴 {n}/{limit}]"
    if n / limit > 0.85:
        return f":orange[🟡 {n}/{limit}]"
    return f":green[🟢 {n}/{limit}]"


def _normalize_id(raw: str) -> str:
    import re
    return re.sub(r"\D", "", raw)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar():
    with st.sidebar:
        st.title("⚙️ Setup")

        anthropic_ok = bool(_get_anthropic_key())
        ads_creds = _get_google_ads_creds()
        ads_ok = bool(ads_creds)

        st.markdown("**API Status**")
        st.markdown(
            f"{'✅' if anthropic_ok else '❌'} Anthropic API "
            f"{'connected' if anthropic_ok else '**not configured**'}"
        )
        st.markdown(
            f"{'✅' if ads_ok else '⚠️'} Google Ads API "
            f"{'connected' if ads_ok else '**not configured** (generate-only mode)'}"
        )
        if ads_ok:
            mcc_id = str(ads_creds.get("login_customer_id", "—"))
            st.caption(f"MCC: {mcc_id}")

        st.divider()

        st.warning(
            "⚠️ **Asset assignment level not decided.**\n\n"
            "Assets are pushed to the account but are **not assigned** to any "
            "campaign or ad group. Decide before running:\n"
            "- Account level\n- Campaign level\n- Manual assignment"
        )

        st.divider()

        with st.expander("📋 How to configure secrets"):
            st.markdown("""
**Local development**

Copy `.streamlit/secrets.toml.example` → `.streamlit/secrets.toml`
and fill in your credentials.

**Streamlit Cloud**

1. Deploy your repo to [streamlit.io](https://streamlit.io)
2. Go to **App Settings → Secrets**
3. Paste the contents of `secrets.toml.example` with your real values

**Required secrets:**
```toml
ANTHROPIC_API_KEY = "sk-ant-..."

[google_ads]
developer_token   = "..."
client_id         = "..."
client_secret     = "..."
refresh_token     = "..."
login_customer_id = "..."  # MCC account ID, digits only

[accounts]
"1234567890" = "Brand A - UK"
```
            """)


# ---------------------------------------------------------------------------
# MCC account loading
# ---------------------------------------------------------------------------

def _load_mcc_accounts(ads_creds: dict):
    """Fetch child accounts from MCC and store in session_state['mcc_accounts']."""
    from google_ads_assets import init_google_ads_client_from_dict, list_child_accounts

    mcc_id = str(ads_creds.get("login_customer_id", "")).replace("-", "")
    with st.spinner("Fetching accounts from MCC ..."):
        try:
            client = init_google_ads_client_from_dict(ads_creds)
            accounts = list_child_accounts(client, mcc_id)
            st.session_state["mcc_accounts"] = accounts
            # Clear downstream state so switching account starts fresh
            for k in ("sitelinks", "callouts", "snippets", "push_results",
                      "scraped_data", "selected_account"):
                st.session_state.pop(k, None)
            for k in list(st.session_state.keys()):
                if k.startswith(("sl_", "co_", "sn_")):
                    del st.session_state[k]
        except RuntimeError as e:
            st.error(f"Could not load accounts: {e}")
            return
    st.rerun()


# ---------------------------------------------------------------------------
# Step 1 — Inputs (URL + account selector)
# ---------------------------------------------------------------------------

def render_inputs() -> tuple[str, str, str]:
    """
    Render URL input and account selector.
    Returns (url, account_id, account_name).
    """
    st.markdown("## 1. Select Website & Account")

    # --- Website URL ---
    url = st.text_input(
        "Website URL",
        placeholder="https://example.com",
        key="url_input",
    )

    st.markdown("**Google Ads Account**")

    ads_creds = _get_google_ads_creds()

    if ads_creds:
        # --- MCC-driven account selector ---
        sel_col, btn_col = st.columns([4, 1])

        with btn_col:
            st.markdown("&nbsp;", unsafe_allow_html=True)  # vertical alignment nudge
            if st.button("🔄 Load Accounts", help="Fetch all child accounts from your MCC"):
                _load_mcc_accounts(ads_creds)

        accounts = st.session_state.get("mcc_accounts")

        if accounts is None:
            with sel_col:
                st.info("Click **Load Accounts** to fetch your accounts from the MCC.")
            return url.strip(), "", ""

        if not accounts:
            with sel_col:
                st.warning("No enabled child accounts found under the MCC.")
            return url.strip(), "", ""

        def _fmt(i: int) -> str:
            a = accounts[i]
            return f"{a['name']}  ({a['id']})  —  {a['currency']}  ·  {a['timezone']}"

        with sel_col:
            idx = st.selectbox(
                "Select account",
                options=range(len(accounts)),
                format_func=_fmt,
                key="account_select_idx",
                label_visibility="collapsed",
            )

        selected = accounts[idx]
        st.session_state["selected_account"] = selected

        # Show a compact info badge for the selected account
        st.caption(
            f"ID: `{selected['id']}`  ·  "
            f"Currency: **{selected['currency']}**  ·  "
            f"Timezone: {selected['timezone']}"
        )
        return url.strip(), selected["id"], selected["name"]

    else:
        # --- Fallback: manual text input (no Ads credentials) ---
        account_id_raw = st.text_input(
            "Account ID",
            placeholder="123-456-7890",
            key="account_id_input",
        )
        norm_id = _normalize_id(account_id_raw)
        known_accounts = _get_accounts()
        name = known_accounts.get(norm_id, norm_id or "Unknown Account")
        return url.strip(), norm_id, name


# ---------------------------------------------------------------------------
# Step 2 — Scrape
# ---------------------------------------------------------------------------

def render_scrape_button(url: str, account_id: str):
    if not url:
        st.info("Enter a website URL to get started.")
        return
    if not account_id:
        st.info("Select a Google Ads account before scraping.")
        return

    if st.button("🔍 Scrape Website", type="primary"):
        _run_scrape(url)


def _run_scrape(url: str):
    from scraper import scrape_site, ScraperError

    with st.spinner(f"Scraping {url} ..."):
        try:
            data = scrape_site(url)
        except ScraperError as e:
            st.error(f"Scraping failed: {e}")
            return
        except Exception as e:
            st.error(f"Unexpected error while scraping: {e}")
            return

    st.session_state["scraped_data"] = data
    for key in ("sitelinks", "callouts", "snippets", "push_results"):
        st.session_state.pop(key, None)
    for k in list(st.session_state.keys()):
        if k.startswith(("sl_", "co_", "sn_")):
            del st.session_state[k]
    st.rerun()


def render_scrape_summary():
    data = st.session_state.get("scraped_data")
    if not data:
        return

    st.success("Website scraped successfully.")
    st.markdown("### Scraped Data Summary")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Brand", data.get("brand_name") or "—")
    col2.metric("Language", data.get("language") or "—")
    col3.metric("Currency", data.get("currency") or "—")
    col4.metric("Nav pages found", len(data.get("nav_pages", [])))

    trust = data.get("trust_signals", [])
    if trust:
        with st.expander(f"Trust signals ({len(trust)})"):
            for s in trust:
                st.markdown(f"- {s}")

    secondary = {k: v for k, v in data.get("secondary_pages", {}).items() if v}
    if secondary:
        with st.expander(f"Secondary pages found ({len(secondary)})"):
            for slug, page in secondary.items():
                st.markdown(f"- **{slug}**: [{page.get('url_path', '')}]({page.get('url', '')})")

    if data.get("scrape_errors"):
        with st.expander("⚠️ Scrape warnings"):
            for err in data["scrape_errors"]:
                st.warning(err)


# ---------------------------------------------------------------------------
# Step 3 — Generate with Claude
# ---------------------------------------------------------------------------

def render_generate_button(account_id: str, account_name: str):
    if "scraped_data" not in st.session_state:
        return

    anthropic_key = _get_anthropic_key()
    if not anthropic_key:
        st.error(
            "Anthropic API key not configured. "
            "Add `ANTHROPIC_API_KEY` to your secrets."
        )
        return

    st.markdown("## 2. Generate Assets with Claude")
    st.caption(f"Generating for: **{account_name}** (`{account_id}`)")

    if st.button("✨ Generate Assets", type="primary"):
        _run_generate(anthropic_key, account_name)


def _run_generate(anthropic_key: str, account_name: str):
    from google_ads_assets import generate_assets_with_claude, validate_assets

    os.environ["ANTHROPIC_API_KEY"] = anthropic_key
    data = st.session_state["scraped_data"]

    with st.spinner("Generating ad assets with Claude ... (this takes ~15 seconds)"):
        try:
            raw = generate_assets_with_claude(data, account_name)
        except SystemExit as e:
            st.error(f"Claude generation failed: {e}")
            return
        except Exception as e:
            st.error(f"Unexpected error during generation: {e}")
            return

    assets, warnings = validate_assets(raw)

    if warnings:
        with st.expander(f"⚠️ {len(warnings)} validation warning(s)"):
            for w in warnings:
                st.warning(w)

    st.session_state["sitelinks"] = assets.get("sitelinks", [])
    st.session_state["callouts"] = assets.get("callouts", [])
    st.session_state["snippets"] = assets.get("structured_snippets", [])
    st.session_state.pop("push_results", None)
    st.rerun()


# ---------------------------------------------------------------------------
# Step 4 — Asset editor
# ---------------------------------------------------------------------------

SITELINK_TITLE_LIMIT = 25
SITELINK_DESC_LIMIT = 35
CALLOUT_LIMIT = 25
SNIPPET_VAL_LIMIT = 25


def render_assets():
    if "sitelinks" not in st.session_state:
        return

    st.markdown("## 3. Review & Edit Assets")
    st.caption(
        "All fields are editable. Character limits are enforced by the input boxes. "
        "🟢 = within limit  🟡 = close to limit  🔴 = over limit"
    )

    _render_sitelinks_editor()
    _render_callouts_editor()
    _render_snippets_editor()


def _render_sitelinks_editor():
    sitelinks = st.session_state["sitelinks"]
    st.markdown(f"### Sitelinks ({len(sitelinks)})")

    for i, sl in enumerate(sitelinks):
        title_key = f"sl_{i}_title"
        d1_key = f"sl_{i}_d1"
        d2_key = f"sl_{i}_d2"
        url_key = f"sl_{i}_url"

        if title_key not in st.session_state:
            st.session_state[title_key] = sl.get("title", "")
            st.session_state[d1_key] = sl.get("description1", "")
            st.session_state[d2_key] = sl.get("description2", "")
            st.session_state[url_key] = sl.get("final_url", "")

        title_val = st.session_state[title_key]
        label = f"Sitelink {i + 1} — {title_val}" if title_val else f"Sitelink {i + 1}"

        with st.expander(label, expanded=(i == 0)):
            col1, col2, col3 = st.columns(3)

            with col1:
                st.text_input("Title", max_chars=SITELINK_TITLE_LIMIT, key=title_key)
                st.caption(_char_label(st.session_state[title_key], SITELINK_TITLE_LIMIT))

            with col2:
                st.text_input("Description line 1", max_chars=SITELINK_DESC_LIMIT, key=d1_key)
                st.caption(_char_label(st.session_state[d1_key], SITELINK_DESC_LIMIT))

            with col3:
                st.text_input("Description line 2", max_chars=SITELINK_DESC_LIMIT, key=d2_key)
                st.caption(_char_label(st.session_state[d2_key], SITELINK_DESC_LIMIT))

            st.text_input("Final URL", key=url_key)


def _render_callouts_editor():
    callouts = st.session_state["callouts"]
    st.markdown(f"### Callouts ({len(callouts)})")

    cols = st.columns(3)
    for i, text in enumerate(callouts):
        key = f"co_{i}"
        if key not in st.session_state:
            st.session_state[key] = text
        with cols[i % 3]:
            st.text_input(f"Callout {i + 1}", max_chars=CALLOUT_LIMIT, key=key)
            st.caption(_char_label(st.session_state[key], CALLOUT_LIMIT))


def _render_snippets_editor():
    snippets = st.session_state["snippets"]
    st.markdown(f"### Structured Snippets ({len(snippets)})")

    for i, snippet in enumerate(snippets):
        header_key = f"sn_{i}_header"
        if header_key not in st.session_state:
            st.session_state[header_key] = snippet.get("header", "")

        header = st.session_state[header_key]
        with st.expander(f"Snippet {i + 1} — {header}", expanded=True):
            st.text_input("Header", key=header_key)

            values = snippet.get("values", [])
            val_cols = st.columns(min(len(values), 5))
            for j, val in enumerate(values):
                val_key = f"sn_{i}_val_{j}"
                if val_key not in st.session_state:
                    st.session_state[val_key] = val
                with val_cols[j % 5]:
                    st.text_input(f"Value {j + 1}", max_chars=SNIPPET_VAL_LIMIT, key=val_key)
                    st.caption(_char_label(st.session_state[val_key], SNIPPET_VAL_LIMIT))


def _collect_edited_assets() -> dict:
    """Read all editor session_state values back into an asset dict."""
    sitelinks = []
    for i in range(len(st.session_state.get("sitelinks", []))):
        title = st.session_state.get(f"sl_{i}_title", "").strip()
        url = st.session_state.get(f"sl_{i}_url", "").strip()
        if title and url:
            sitelinks.append({
                "title": title,
                "description1": st.session_state.get(f"sl_{i}_d1", "").strip(),
                "description2": st.session_state.get(f"sl_{i}_d2", "").strip(),
                "final_url": url,
            })

    callouts = [
        st.session_state.get(f"co_{i}", "").strip()
        for i in range(len(st.session_state.get("callouts", [])))
        if st.session_state.get(f"co_{i}", "").strip()
    ]

    snippets = []
    for i in range(len(st.session_state.get("snippets", []))):
        header = st.session_state.get(f"sn_{i}_header", "").strip()
        n_vals = len(st.session_state["snippets"][i].get("values", []))
        values = [
            st.session_state.get(f"sn_{i}_val_{j}", "").strip()
            for j in range(n_vals)
            if st.session_state.get(f"sn_{i}_val_{j}", "").strip()
        ]
        if header and values:
            snippets.append({"header": header, "values": values})

    return {"sitelinks": sitelinks, "callouts": callouts, "structured_snippets": snippets}


# ---------------------------------------------------------------------------
# Step 5 — Push to Google Ads
# ---------------------------------------------------------------------------

def render_push_section(account_id: str, account_name: str):
    if "sitelinks" not in st.session_state:
        return

    ads_creds = _get_google_ads_creds()
    st.markdown("## 4. Push to Google Ads")

    if account_id and account_name:
        st.caption(f"Target: **{account_name}** (`{account_id}`)")

    col1, col2 = st.columns(2)
    with col1:
        push_disabled = not ads_creds or not account_id
        push_help = (
            "Google Ads credentials not configured." if not ads_creds
            else ("No account selected." if not account_id else None)
        )
        if st.button(
            "🚀 Push to Google Ads",
            type="primary",
            disabled=push_disabled,
            help=push_help,
        ):
            _run_push(ads_creds, account_id)

    with col2:
        if st.button("🔄 Regenerate Assets"):
            for key in ("sitelinks", "callouts", "snippets", "push_results"):
                st.session_state.pop(key, None)
            for k in list(st.session_state.keys()):
                if k.startswith(("sl_", "co_", "sn_")):
                    del st.session_state[k]
            st.rerun()

    if not ads_creds:
        st.info(
            "Google Ads credentials not configured. "
            "Assets were generated successfully — see below for manual creation."
        )
        _render_fallback_assets()


def _run_push(ads_creds: dict, account_id: str):
    from google_ads_assets import (
        fetch_existing_assets,
        init_google_ads_client_from_dict,
        push_callouts,
        push_sitelinks,
        push_structured_snippets,
        validate_assets,
    )

    norm_id = _normalize_id(account_id)
    assets = _collect_edited_assets()
    cleaned, warnings = validate_assets(assets)

    if warnings:
        for w in warnings:
            st.warning(w)

    with st.spinner(f"Pushing assets to account {norm_id} ..."):
        try:
            client = init_google_ads_client_from_dict(ads_creds)
        except RuntimeError as e:
            st.error(f"Google Ads connection failed: {e}")
            return

        try:
            existing = fetch_existing_assets(client, norm_id)
        except Exception as e:
            st.error(f"Could not fetch existing assets: {e}")
            return

        results = {}
        for asset_type, push_fn, items in [
            ("sitelinks", push_sitelinks, cleaned["sitelinks"]),
            ("callouts", push_callouts, cleaned["callouts"]),
            ("structured_snippets", push_structured_snippets, cleaned["structured_snippets"]),
        ]:
            try:
                results[asset_type] = push_fn(client, norm_id, items, existing)
            except Exception as e:
                st.error(f"Failed to push {asset_type}: {e}")
                results[asset_type] = {
                    "created": 0, "skipped": 0,
                    "failed": len(items), "failed_items": [],
                }

    st.session_state["push_results"] = results
    st.rerun()


def render_push_results(account_id: str, account_name: str):
    results = st.session_state.get("push_results")
    if not results:
        return

    sl = results.get("sitelinks", {})
    co = results.get("callouts", {})
    sn = results.get("structured_snippets", {})
    total = sl.get("created", 0) + co.get("created", 0) + sn.get("created", 0)

    st.markdown("## Results")
    st.success(
        f"Push complete — **{total} assets created** "
        f"for **{account_name}** (`{account_id}`)"
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("Sitelinks", f"✓ {sl.get('created', 0)} created",
                f"⊘ {sl.get('skipped', 0)} skipped  ✗ {sl.get('failed', 0)} failed")
    col2.metric("Callouts", f"✓ {co.get('created', 0)} created",
                f"⊘ {co.get('skipped', 0)} skipped  ✗ {co.get('failed', 0)} failed")
    col3.metric("Snippets", f"✓ {sn.get('created', 0)} created",
                f"⊘ {sn.get('skipped', 0)} skipped  ✗ {sn.get('failed', 0)} failed")

    all_failed = (
        sl.get("failed_items", []) +
        co.get("failed_items", []) +
        sn.get("failed_items", [])
    )
    if all_failed:
        with st.expander(f"✗ {len(all_failed)} failed asset(s)"):
            for item in all_failed:
                st.markdown(f"- {item}")

    st.warning(
        "⚠️ **Reminder:** Assets have been created in the account but are **not yet "
        "assigned** to any campaign or ad group. Please decide on assignment level "
        "(account-wide, campaign-level, or manual) in Google Ads."
    )


def _render_fallback_assets():
    """Show assets as plain text for manual creation when Ads API is unavailable."""
    if "sitelinks" not in st.session_state:
        return

    assets = _collect_edited_assets()

    with st.expander("📋 Assets for manual creation"):
        st.markdown("**SITELINKS**")
        for sl in assets["sitelinks"]:
            st.markdown(
                f"- **{sl['title']}** → `{sl['final_url']}`  \n"
                f"  _{sl.get('description1', '')}_ | _{sl.get('description2', '')}_"
            )

        st.markdown("**CALLOUTS**")
        if assets["callouts"]:
            st.markdown("  |  ".join(f"`{c}`" for c in assets["callouts"]))

        st.markdown("**STRUCTURED SNIPPETS**")
        for sn in assets["structured_snippets"]:
            vals = ", ".join(sn["values"])
            st.markdown(f"- **{sn['header']}**: {vals}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    render_sidebar()

    st.title("🎯 Google Ads Asset Builder")
    st.caption(
        "Scrape a website, generate sitelinks / callouts / structured snippets with Claude, "
        "and push them directly to a Google Ads account."
    )
    st.divider()

    url, account_id, account_name = render_inputs()

    st.divider()
    render_scrape_button(url, account_id)
    render_scrape_summary()

    if st.session_state.get("scraped_data"):
        st.divider()
        render_generate_button(account_id, account_name)

    if st.session_state.get("sitelinks") is not None:
        st.divider()
        render_assets()
        st.divider()
        render_push_section(account_id, account_name)

    if st.session_state.get("push_results"):
        st.divider()
        render_push_results(account_id, account_name)


if __name__ == "__main__":
    main()
