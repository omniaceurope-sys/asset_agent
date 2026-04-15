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
    """Return Google Ads credentials dict from secrets or config file."""
    try:
        creds = dict(st.secrets["google_ads"])
        # Reject placeholder values
        if str(creds.get("developer_token", "")).startswith("X"):
            return None
        return creds
    except (KeyError, FileNotFoundError):
        pass

    # Fallback: read local config/google_ads.yaml
    config_path = Path(__file__).parent / "config" / "google_ads.yaml"
    if config_path.exists():
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            creds = yaml.safe_load(f)
        if creds and not str(creds.get("developer_token", "X")).startswith("X"):
            return creds
    return None


def _get_accounts() -> dict:
    """Return {account_id: name} from secrets or config file."""
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

def _char_color(n: int, limit: int) -> str:
    """Return a color string based on character usage."""
    if n > limit:
        return "red"
    if n / limit > 0.85:
        return "orange"
    return "green"


def _char_label(text: str, limit: int) -> str:
    """Return a colored markdown character-count badge."""
    n = len(text)
    color = _char_color(n, limit)
    icon = "🔴" if n > limit else ("🟡" if n / limit > 0.85 else "🟢")
    return f":{color}[{icon} {n}/{limit}]"


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
        ads_ok = bool(_get_google_ads_creds())

        st.markdown("**API Status**")
        st.markdown(
            f"{'✅' if anthropic_ok else '❌'} Anthropic API "
            f"{'connected' if anthropic_ok else '**not configured**'}"
        )
        st.markdown(
            f"{'✅' if ads_ok else '⚠️'} Google Ads API "
            f"{'connected' if ads_ok else '**not configured** (generate-only mode)'}"
        )

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
# Step 1 — Inputs
# ---------------------------------------------------------------------------

def render_inputs() -> tuple[str, str]:
    st.markdown("## 1. Enter Website & Account")
    col1, col2 = st.columns([2, 1])
    with col1:
        url = st.text_input(
            "Website URL",
            placeholder="https://example.com",
            value=st.session_state.get("url_input", ""),
            key="url_input",
        )
    with col2:
        account_id = st.text_input(
            "Google Ads Account ID",
            placeholder="123-456-7890",
            value=st.session_state.get("account_id_input", ""),
            key="account_id_input",
        )
    return url.strip(), account_id.strip()


# ---------------------------------------------------------------------------
# Step 2 — Scrape
# ---------------------------------------------------------------------------

def render_scrape_button(url: str, account_id: str):
    if not url:
        st.info("Enter a website URL to get started.")
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
    # Clear downstream state when re-scraping
    for key in ("sitelinks", "callouts", "snippets", "push_results"):
        st.session_state.pop(key, None)
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

def render_generate_button(account_id: str):
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

    accounts = _get_accounts()
    norm_id = _normalize_id(account_id) if account_id else ""
    account_name = accounts.get(norm_id, norm_id or "Unknown Account")

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

    # Store in session state as editable copies
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

        # Seed defaults on first render
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
                st.text_input(
                    "Title",
                    max_chars=SITELINK_TITLE_LIMIT,
                    key=title_key,
                )
                st.caption(_char_label(st.session_state[title_key], SITELINK_TITLE_LIMIT))

            with col2:
                st.text_input(
                    "Description line 1",
                    max_chars=SITELINK_DESC_LIMIT,
                    key=d1_key,
                )
                st.caption(_char_label(st.session_state[d1_key], SITELINK_DESC_LIMIT))

            with col3:
                st.text_input(
                    "Description line 2",
                    max_chars=SITELINK_DESC_LIMIT,
                    key=d2_key,
                )
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
            st.text_input(
                f"Callout {i + 1}",
                max_chars=CALLOUT_LIMIT,
                key=key,
            )
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
                    st.text_input(
                        f"Value {j + 1}",
                        max_chars=SNIPPET_VAL_LIMIT,
                        key=val_key,
                    )
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

def render_push_section(account_id: str):
    if "sitelinks" not in st.session_state:
        return

    ads_creds = _get_google_ads_creds()
    st.markdown("## 4. Push to Google Ads")

    col1, col2 = st.columns(2)
    with col1:
        push_disabled = not ads_creds or not account_id
        push_help = (
            "Google Ads credentials not configured."
            if not ads_creds
            else ("Enter an account ID above." if not account_id else None)
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
            # Clear editor keys
            for k in list(st.session_state.keys()):
                if k.startswith(("sl_", "co_", "sn_")):
                    del st.session_state[k]
            st.rerun()

    if not ads_creds:
        st.info(
            "Google Ads credentials not configured. "
            "The assets above were generated successfully and can be created manually. "
            "See the sidebar for setup instructions."
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

    with st.spinner("Connecting to Google Ads and pushing assets ..."):
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
        try:
            results["sitelinks"] = push_sitelinks(
                client, norm_id, cleaned["sitelinks"], existing
            )
        except Exception as e:
            st.error(f"Failed to push sitelinks: {e}")
            results["sitelinks"] = {"created": 0, "skipped": 0, "failed": len(cleaned["sitelinks"]), "failed_items": []}

        try:
            results["callouts"] = push_callouts(
                client, norm_id, cleaned["callouts"], existing
            )
        except Exception as e:
            st.error(f"Failed to push callouts: {e}")
            results["callouts"] = {"created": 0, "skipped": 0, "failed": len(cleaned["callouts"]), "failed_items": []}

        try:
            results["structured_snippets"] = push_structured_snippets(
                client, norm_id, cleaned["structured_snippets"], existing
            )
        except Exception as e:
            st.error(f"Failed to push structured snippets: {e}")
            results["structured_snippets"] = {"created": 0, "skipped": 0, "failed": len(cleaned["structured_snippets"]), "failed_items": []}

    st.session_state["push_results"] = results
    st.rerun()


def render_push_results(account_id: str):
    results = st.session_state.get("push_results")
    if not results:
        return

    st.markdown("## Results")
    accounts = _get_accounts()
    norm_id = _normalize_id(account_id) if account_id else ""
    account_name = accounts.get(norm_id, norm_id or "—")

    sl = results.get("sitelinks", {})
    co = results.get("callouts", {})
    sn = results.get("structured_snippets", {})
    total = sl.get("created", 0) + co.get("created", 0) + sn.get("created", 0)

    st.success(f"Push complete — **{total} assets created** for account {norm_id} ({account_name})")

    col1, col2, col3 = st.columns(3)
    col1.metric("Sitelinks", f"✓ {sl.get('created',0)} created",
                f"⊘ {sl.get('skipped',0)} skipped  ✗ {sl.get('failed',0)} failed")
    col2.metric("Callouts", f"✓ {co.get('created',0)} created",
                f"⊘ {co.get('skipped',0)} skipped  ✗ {co.get('failed',0)} failed")
    col3.metric("Snippets", f"✓ {sn.get('created',0)} created",
                f"⊘ {sn.get('skipped',0)} skipped  ✗ {sn.get('failed',0)} failed")

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
    """Show assets as plain text when Google Ads is not configured."""
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
        "Scrape a website, generate sitelinks/callouts/snippets with Claude, "
        "and push them directly to Google Ads."
    )
    st.divider()

    url, account_id = render_inputs()

    st.divider()
    render_scrape_button(url, account_id)
    render_scrape_summary()

    if st.session_state.get("scraped_data"):
        st.divider()
        render_generate_button(account_id)

    if st.session_state.get("sitelinks") is not None:
        st.divider()
        render_assets()
        st.divider()
        render_push_section(account_id)

    if st.session_state.get("push_results"):
        st.divider()
        render_push_results(account_id)


if __name__ == "__main__":
    main()
