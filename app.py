"""Simple CRM — run with:  streamlit run app.py"""

from __future__ import annotations

from pathlib import Path

import gspread
import requests
import streamlit as st
from google.auth import exceptions as google_auth_errors

import views
from sheets import CRMStore, SetupError, credentials_path, load_config, open_spreadsheet, sheet_key_from

st.set_page_config(page_title="Simple CRM", page_icon=":material/contacts:", layout="centered")


@st.cache_resource(show_spinner="Connecting to Google Sheets…")
def _connect(creds_file: str, creds_mtime: float, sheet_key: str) -> CRMStore:
    return CRMStore(open_spreadsheet(Path(creds_file), sheet_key))


def get_store() -> tuple[CRMStore | None, str | None]:
    """Return (store, error). Both are None when setup hasn't been done yet."""
    cfg = load_config()
    key = sheet_key_from(cfg.get("sheet_url", ""))
    creds = credentials_path(cfg)
    if not key or not creds.exists():
        return None, None
    signature = (str(creds), creds.stat().st_mtime, key)
    try:
        return _connect(*signature), None
    except SetupError as exc:  # not cached, so the next page load tries again
        return None, str(exc)


store, error = get_store()

if store is None:
    setup = st.Page(lambda: views.setup_page(None, error), title="Setup", icon=":material/settings:",
                    url_path="setup")
    views.PAGES.clear()
    views.PAGES["setup"] = setup
    page = st.navigation([setup])
else:
    views.PAGES.update(
        customers=st.Page(lambda: views.customers_page(store), title="Customers",
                          icon=":material/group:", url_path="customers", default=True),
        log=st.Page(lambda: views.log_page(store), title="Log Interaction",
                    icon=":material/edit_note:", url_path="log"),
        history=st.Page(lambda: views.history_page(store), title="Customer History",
                        icon=":material/history:", url_path="history"),
        setup=st.Page(lambda: views.setup_page(store, None), title="Settings",
                      icon=":material/settings:", url_path="setup"),
    )
    page = st.navigation(list(views.PAGES.values()))
    if st.session_state.pop("just_connected", False):
        st.switch_page(views.PAGES["customers"])
    with st.sidebar:
        st.caption(f"Saving to **{store.title}**")
        st.link_button("Open Google Sheet", store.url, icon=":material/open_in_new:", width="stretch")
        if st.button("Refresh from sheet", icon=":material/refresh:", width="stretch",
                     help="Reload after editing the Google Sheet directly."):
            views.refresh_data()

try:
    page.run()
except gspread.exceptions.APIError as exc:
    if exc.code == 429:
        st.error("Google Sheets is rate-limiting requests. Wait a minute, then click Refresh.",
                 icon=":material/hourglass:")
    else:
        st.error(f"Google Sheets returned an error: {exc}. If you changed sharing or deleted the sheet, "
                 "fix it on the Settings page.", icon=":material/error:")
except (google_auth_errors.GoogleAuthError, requests.exceptions.RequestException) as exc:
    st.error(f"Couldn't reach Google Sheets. Check your internet connection. Details: {exc}",
             icon=":material/wifi_off:")
