"""The CRM's pages: Customers (add + list), Log Interaction, Customer History, and Setup."""

from __future__ import annotations

import html
import json
import os
import re
from datetime import date

import pandas as pd
import streamlit as st

from sheets import (
    CONFIG_PATH,
    INTERACTION_TYPES,
    CRMStore,
    SetupError,
    clean_phone,
    credentials_path,
    load_config,
    parse_date,
    phone_digits,
    save_config,
    sheet_key_from,
    validate_service_account,
)

# Filled in by app.py on every run so pages can link to each other.
PAGES: dict = {}

TYPE_COLORS = {
    "Call": "#3b82f6",
    "Email": "#a855f7",
    "Meeting": "#22a55a",
    "Site Visit": "#f08c00",
    "Text Message": "#06a6b8",
    "Other": "#8a94a3",
}


# ------------------------------------------------------------------ cached reads

@st.cache_data(ttl=60, show_spinner=False)
def load_customers(_store: CRMStore, sheet_id: str) -> pd.DataFrame:
    return _store.customers()


@st.cache_data(ttl=60, show_spinner=False)
def load_interactions(_store: CRMStore, sheet_id: str) -> pd.DataFrame:
    return _store.interactions()


def refresh_data() -> None:
    load_customers.clear()
    load_interactions.clear()


def _data(store: CRMStore) -> tuple[pd.DataFrame, pd.DataFrame]:
    return load_customers(store, store.sheet.id), load_interactions(store, store.sheet.id)


# ----------------------------------------------------------------------- helpers

def _flash(msg: str, link: str | None = None, link_label: str | None = None) -> None:
    st.session_state["flash"] = {"msg": msg, "link": link, "link_label": link_label}


def _show_flash() -> None:
    flash = st.session_state.pop("flash", None)
    if not flash:
        return
    st.success(flash["msg"], icon=":material/check_circle:")
    if flash.get("link") in PAGES:
        st.page_link(PAGES[flash["link"]], label=flash["link_label"], icon=":material/arrow_forward:")


def _fmt_date(value, long: bool = False) -> str:
    if value is None or pd.isna(value):
        return "—"
    text = f"{value:%b} {value.day}, {value.year}"
    return f"{value:%a}, {text}" if long else text


def _ago(day: date) -> str:
    days = (date.today() - day).days
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days == -1:
        return "tomorrow"
    if days < 0:
        return f"in {-days} days"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"{days // 7} weeks ago"
    if days < 730:
        return f"{days // 30} months ago"
    return f"{days // 365} years ago"


def _linked_customers(customers: pd.DataFrame) -> pd.DataFrame:
    """Customers that have an ID (rows typed into the sheet without one can't be linked)."""
    linked = customers[customers["Customer ID"] != ""]
    return linked.sort_values("Name", key=lambda s: s.str.lower()).drop_duplicates("Customer ID")


def _customer_picker(customers: pd.DataFrame, key: str) -> str:
    """Customer dropdown that remembers the same customer across all pages."""
    ids = customers["Customer ID"].tolist()
    labels = {
        r["Customer ID"]: f"{r['Name'] or '(no name)'}  ·  {r['Phone'] or r['Customer ID']}"
        for _, r in customers.iterrows()
    }
    active = st.session_state.get("active_customer_id")
    if active not in ids:
        active = ids[0]
        st.session_state["active_customer_id"] = active
    st.session_state[key] = active

    def _sync():
        st.session_state["active_customer_id"] = st.session_state[key]

    return st.selectbox("Customer", ids, format_func=labels.get, key=key, on_change=_sync)


def _history_for(interactions: pd.DataFrame, customer_id: str, newest_first: bool) -> pd.DataFrame:
    hist = interactions[interactions["Customer ID"] == customer_id].copy()
    hist = hist.sort_values(["when", "logged"], ascending=True, na_position="first", kind="stable")
    hist["number"] = range(1, len(hist) + 1)
    if newest_first:
        hist = hist.iloc[::-1]
    return hist


def _need_customers_first() -> None:
    st.info("No customers yet. Add your first customer, then come back here.", icon=":material/info:")
    st.page_link(PAGES["customers"], label="Add a customer", icon=":material/person_add:")


# ------------------------------------------------------------------- timeline UI

_TIMELINE_CSS = """
<style>
.crm-tl { position: relative; margin: 0.25rem 0 0 0.4rem; padding-left: 1.6rem;
          border-left: 2px solid rgba(128,128,128,0.28); }
.crm-item { position: relative; margin-bottom: 1rem; }
.crm-item:last-child { margin-bottom: 0.25rem; }
.crm-dot { position: absolute; left: calc(-1.6rem - 7px); top: 1.05rem; width: 12px; height: 12px;
           border-radius: 50%; box-shadow: 0 0 0 4px rgba(128,128,128,0.14); }
.crm-card { border: 1px solid rgba(128,128,128,0.25); border-radius: 0.6rem;
            padding: 0.75rem 1rem 0.85rem; background: rgba(128,128,128,0.05); }
.crm-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; font-size: 0.9rem; }
.crm-date { font-weight: 600; }
.crm-chip { font-size: 0.75rem; font-weight: 600; padding: 0.1rem 0.55rem; border-radius: 999px;
            border: 1px solid; }
.crm-ago, .crm-num { opacity: 0.6; font-size: 0.82rem; }
.crm-num { margin-left: auto; }
.crm-body { margin-top: 0.45rem; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.55; }
</style>
"""


def _timeline(hist: pd.DataFrame) -> str:
    items = []
    for _, r in hist.iterrows():
        kind = r["Type"] or "Other"
        color = TYPE_COLORS.get(kind, TYPE_COLORS["Other"])
        when = r["when"]
        if pd.isna(when):
            date_txt, ago = html.escape(r["Date"] or "No date"), ""
        else:
            date_txt, ago = _fmt_date(when, long=True), _ago(when.date())
        body = html.escape(r["Content"]) if r["Content"] else "<em style='opacity:.6'>No notes</em>"
        items.append(
            f"<div class='crm-item'><div class='crm-dot' style='background:{color}'></div>"
            f"<div class='crm-card'><div class='crm-meta'>"
            f"<span class='crm-date'>{date_txt}</span>"
            f"<span class='crm-chip' style='color:{color};border-color:{color}66;background:{color}1f'>"
            f"{html.escape(kind)}</span>"
            f"<span class='crm-ago'>{ago}</span><span class='crm-num'>#{r['number']}</span></div>"
            f"<div class='crm-body'>{body}</div></div></div>"
        )
    return _TIMELINE_CSS + "<div class='crm-tl'>" + "".join(items) + "</div>"


# ------------------------------------------------------------------------- pages

def customers_page(store: CRMStore) -> None:
    st.title("Customers")
    _show_flash()
    customers, interactions = _data(store)

    if st.session_state.pop("reset_customer_form", False):
        for k in ("cust_name", "cust_phone", "cust_address"):
            st.session_state[k] = ""

    with st.form("add_customer"):
        st.subheader("Add a customer")
        name = st.text_input("Full name *", key="cust_name", placeholder="Jane Doe")
        c1, c2 = st.columns([2, 3])
        phone = c1.text_input("Phone number", key="cust_phone", placeholder="(301) 555-0123")
        address = c2.text_input("Address", key="cust_address", placeholder="123 Main St, Rockville, MD 20850")
        submitted = st.form_submit_button("Add customer", type="primary", icon=":material/person_add:")

    if submitted:
        name = " ".join(name.split())
        address = " ".join(address.split())
        phone = clean_phone(phone)
        digits = phone_digits(phone)
        problems = []
        if not name:
            problems.append("Enter the customer's name.")
        if phone and not 7 <= len(digits) <= 15:
            problems.append("That phone number doesn't look right (expected 7–15 digits).")
        dupes = customers[
            (customers["Name"].str.lower() == name.lower())
            & (customers["Phone"].map(phone_digits) == digits)
        ]
        if name and not dupes.empty:
            existing = dupes.iloc[0]["Customer ID"] or "no ID"
            problems.append(
                f"{name} with that phone number is already a customer ({existing})." if digits else
                f"A customer named {name} already exists ({existing}). Add a phone number to tell them apart.")
        for p in problems:
            st.error(p, icon=":material/error:")
        if not problems:
            with st.spinner("Saving to Google Sheets…"):
                rec = store.add_customer(name, address, phone)
            refresh_data()
            st.session_state["active_customer_id"] = rec["Customer ID"]
            st.session_state["reset_customer_form"] = True
            _flash(f"Added {name} ({rec['Customer ID']}).", "log", f"Log an interaction with {name}")
            st.rerun()

    # Customer list, joined with a summary of each customer's interactions.
    st.subheader(f"Customer list ({len(customers)})")
    if customers.empty:
        st.caption("Customers you add appear here and in the Customers tab of your sheet.")
        return
    stats = interactions.groupby("Customer ID").agg(Interactions=("Date", "size"), last=("when", "max"))
    table = customers.merge(stats, how="left", left_on="Customer ID", right_index=True)
    table["Interactions"] = table["Interactions"].fillna(0).astype(int)
    table["Last Contact"] = table["last"]

    query = st.text_input("Search", placeholder="Search name, phone or address",
                          label_visibility="collapsed", key="cust_search")
    if query.strip():
        q = query.strip().lower()
        hit = table[["Name", "Address", "Phone", "Customer ID"]].apply(
            lambda col: col.str.lower().str.contains(q, regex=False)).any(axis=1)
        qd = re.sub(r"\D", "", q)
        if len(qd) >= 3:
            hit |= table["Phone"].map(phone_digits).str.contains(qd, regex=False)
        table = table[hit]

    table = table.sort_values("Name", key=lambda s: s.str.lower())
    shown = table[["Customer ID", "Name", "Phone", "Address", "Interactions", "Last Contact"]]
    event = st.dataframe(
        shown,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key="customer_table",
        placeholder="—",
        column_order=["Name", "Phone", "Address", "Interactions", "Last Contact"],
        column_config={"Last Contact": st.column_config.DateColumn(format="MMM D, YYYY")},
    )
    rows = event.selection.rows if event else []
    if rows:
        picked = shown.iloc[rows[0]]
        c1, c2 = st.columns(2)
        if c1.button(f"View {picked['Name']}'s history", icon=":material/history:", width="stretch"):
            st.session_state["active_customer_id"] = picked["Customer ID"]
            st.switch_page(PAGES["history"])
        if c2.button(f"Log an interaction", icon=":material/edit_note:", width="stretch"):
            st.session_state["active_customer_id"] = picked["Customer ID"]
            st.switch_page(PAGES["log"])
    else:
        st.caption("Select a row to open that customer's history or log an interaction.")


def log_page(store: CRMStore) -> None:
    st.title("Log an interaction")
    _show_flash()
    customers, interactions = _data(store)
    linked = _linked_customers(customers)
    if linked.empty:
        _need_customers_first()
        return

    cid = _customer_picker(linked, key="log_customer")
    cust = linked[linked["Customer ID"] == cid].iloc[0]
    hist = _history_for(interactions, cid, newest_first=True)
    if hist.empty:
        st.caption("No interactions logged with this customer yet.")
    else:
        st.caption(f"{len(hist)} interaction{'s' if len(hist) != 1 else ''} so far · "
                   f"last contact {_fmt_date(hist['when'].max())}")

    if st.session_state.pop("reset_log_form", False):
        st.session_state["log_content"] = ""

    with st.form("log_interaction"):
        c1, c2 = st.columns(2)
        when = c1.date_input("Date of interaction", value=date.today(), format="MM/DD/YYYY", key="log_date")
        kind = c2.selectbox("Type", INTERACTION_TYPES, key="log_type")
        content = st.text_area(
            "What happened?", key="log_content", height=160,
            placeholder="e.g. Called about the spring service quote. Wants a follow-up next Tuesday.",
        )
        submitted = st.form_submit_button("Save interaction", type="primary", icon=":material/save:")

    if submitted:
        if not content.strip():
            st.error("Write a few words about the interaction before saving.", icon=":material/error:")
        else:
            with st.spinner("Saving to Google Sheets…"):
                store.add_interaction(cid, cust["Name"], when, kind, content.strip())
            refresh_data()
            st.session_state["reset_log_form"] = True
            _flash(f"Saved {kind.lower()} with {cust['Name']} on {_fmt_date(pd.Timestamp(when))}.",
                   "history", f"See {cust['Name']}'s full history")
            st.rerun()

    if not hist.empty:
        st.markdown("##### Most recent")
        st.html(_timeline(hist.head(3)))
        if len(hist) > 3:
            st.page_link(PAGES["history"], label=f"See all {len(hist)} interactions",
                         icon=":material/arrow_forward:")


def history_page(store: CRMStore) -> None:
    st.title("Customer history")
    _show_flash()
    customers, interactions = _data(store)
    linked = _linked_customers(customers)
    if linked.empty:
        _need_customers_first()
        return

    cid = _customer_picker(linked, key="history_customer")
    cust = linked[linked["Customer ID"] == cid].iloc[0]
    all_hist = _history_for(interactions, cid, newest_first=False)

    with st.container(border=True):
        st.subheader(cust["Name"] or "(no name)")
        details = [f":material/call: {cust['Phone']}" if cust["Phone"] else None,
                   f":material/location_on: {cust['Address']}" if cust["Address"] else None,
                   f"ID {cust['Customer ID']}"]
        added = parse_date(cust["Date Added"])
        if added:
            details.append(f"customer since {_fmt_date(pd.Timestamp(added))}")
        st.caption("  ·  ".join(d for d in details if d))
        m1, m2, m3 = st.columns(3)
        m1.metric("Interactions", len(all_hist))
        m2.metric("First contact", _fmt_date(all_hist["when"].min()) if not all_hist.empty else "—")
        m3.metric("Last contact", _fmt_date(all_hist["when"].max()) if not all_hist.empty else "—")

    if all_hist.empty:
        st.info(f"No interactions logged with {cust['Name']} yet.", icon=":material/info:")
        st.page_link(PAGES["log"], label="Log the first one", icon=":material/edit_note:")
        return

    c1, c2 = st.columns([3, 2], vertical_alignment="center")
    order = c1.radio("Order", ["Newest first", "Oldest first"], horizontal=True,
                     label_visibility="collapsed", key="history_order")
    types = sorted(t for t in all_hist["Type"].unique() if t)
    shown_types = c2.multiselect("Filter by type", types, placeholder="All types",
                                 label_visibility="collapsed", key="history_types")

    hist = _history_for(interactions, cid, newest_first=(order == "Newest first"))
    if shown_types:
        hist = hist[hist["Type"].isin(shown_types)]
    if hist.empty:
        st.caption("No interactions of that type.")
    else:
        st.html(_timeline(hist))

    b1, b2 = st.columns(2)
    b1.page_link(PAGES["log"], label="Log a new interaction", icon=":material/edit_note:")
    export = hist[["Date", "Type", "Content", "Logged At"]]
    safe_name = re.sub(r"[^\w\- ]", "", cust["Name"]).strip() or cid
    b2.download_button("Download as CSV", export.to_csv(index=False).encode("utf-8"),
                       file_name=f"{safe_name} - history.csv", mime="text/csv",
                       icon=":material/download:", width="stretch")


def setup_page(store: CRMStore | None, error: str | None) -> None:
    st.title("Connect your Google Sheet")
    st.write("Everything this CRM saves goes into a Google Sheet you own, in two tabs: "
             "**Customers** and **Interactions**. This one-time setup takes about 5 minutes.")
    _show_flash()
    if store is not None:
        st.success(f"Connected to **{store.title}**.", icon=":material/check_circle:")
        st.link_button("Open the sheet", store.url, icon=":material/open_in_new:")
    if error:
        st.error(f"Your saved key and sheet link were found, but connecting failed: {error}",
                 icon=":material/error:")
        if st.button("Try again", type="primary", icon=":material/refresh:"):
            st.cache_resource.clear()
            st.session_state["just_connected"] = True
            st.rerun()
        st.caption("No need to re-upload anything unless the message says the key or link is wrong.")

    cfg = load_config()
    creds = credentials_path(cfg)
    email = None
    if creds.exists():
        try:
            email = validate_service_account(json.loads(creds.read_text(encoding="utf-8")))
        except (SetupError, ValueError, OSError) as exc:
            st.warning(f"{creds.name} is there but can't be used: {exc}", icon=":material/warning:")

    st.subheader("1. Get a Google key file")
    with st.expander("How to create a service-account key", expanded=email is None):
        st.markdown(
            "1. Go to **[console.cloud.google.com](https://console.cloud.google.com/)** and sign in. "
            "At the top, click the project picker → **New project** → give it any name → **Create**.\n"
            "2. Open **[Google Sheets API](https://console.cloud.google.com/apis/library/sheets.googleapis.com)** "
            "and click **Enable** (check the new project is selected at the top).\n"
            "3. Go to **[IAM & Admin → Service accounts](https://console.cloud.google.com/iam-admin/serviceaccounts)** "
            "→ **Create service account** → name it `crm` → **Done** (skip the optional steps).\n"
            "4. Click the new service account → **Keys** tab → **Add key** → **Create new key** → "
            "**JSON** → **Create**. A `.json` file downloads.\n"
            "5. Upload that file below. Keep it private: it works like a password to your sheet."
        )
    if email:
        st.success(f"Key file loaded. Service account: `{email}`", icon=":material/key:")
    uploaded = st.file_uploader("Replace key file" if email else "Upload the key file (.json)", type=["json"])
    if uploaded is not None and st.session_state.get("processed_upload") != uploaded.file_id:
        st.session_state["processed_upload"] = uploaded.file_id
        try:
            data = json.loads(uploaded.getvalue().decode("utf-8"))
            new_email = validate_service_account(data)
        except (SetupError, ValueError, UnicodeDecodeError) as exc:
            st.error(str(exc) if isinstance(exc, SetupError) else "That file isn't valid JSON.",
                     icon=":material/error:")
        else:
            target = credentials_path({})
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(data, indent=2), encoding="utf-8")
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
            cfg["credentials_file"] = target.name
            save_config(cfg)
            st.session_state.pop("connect_failure", None)
            st.cache_resource.clear()
            _flash(f"Key saved. Now share your sheet with {new_email}.")
            st.rerun()

    st.subheader("2. Share your sheet with the service account")
    if email:
        st.markdown("Create a blank sheet at **[sheets.new](https://sheets.new)** (or use an existing one), "
                    "click **Share**, and add this address as an **Editor** (untick *Notify people*):")
        st.code(email, language=None)
    else:
        st.caption("Upload the key file first. It contains the email address you share the sheet with.")

    st.subheader("3. Paste the sheet's link")
    url = st.text_input("Google Sheet URL", value=cfg.get("sheet_url", ""),
                        placeholder="https://docs.google.com/spreadsheets/d/…")
    if st.button("Connect", type="primary", icon=":material/link:", disabled=email is None):
        if not sheet_key_from(url):
            st.error("That doesn't look like a Google Sheets link. Copy it from your browser's address bar "
                     "while the sheet is open.", icon=":material/error:")
        else:
            cfg["sheet_url"] = url.strip()
            cfg.setdefault("credentials_file", creds.name)
            save_config(cfg)
            st.session_state.pop("connect_failure", None)
            st.session_state["just_connected"] = True
            st.cache_resource.clear()
            refresh_data()
            st.rerun()
    st.caption("The app creates the Customers and Interactions tabs (with headers) the first time it connects. "
               f"Your key and sheet link are saved in {CONFIG_PATH.parent}, so they're kept between restarts.")
