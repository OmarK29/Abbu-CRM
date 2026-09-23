"""Google Sheets storage for the CRM.

One spreadsheet, two related tabs:
  Customers     Customer ID | Name | Address | Phone | Date Added
  Interactions  Customer ID | Customer Name | Date | Type | Content | Logged At

"Customer ID" links every interaction back to its customer. This module has no
Streamlit code in it, so it can be reused from scripts too.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

import gspread
import pandas as pd
import requests
from gspread.utils import rowcol_to_a1
from google.auth import exceptions as google_auth_errors

APP_DIR = Path(__file__).resolve().parent
# Settings live in your home folder, so they survive restarts, re-downloads and extra copies of the app.
DATA_DIR = Path.home() / ".simple-crm"
CONFIG_PATH = DATA_DIR / "config.json"
DEFAULT_CREDENTIALS_FILE = "service_account.json"

CUSTOMERS_TAB = "Customers"
INTERACTIONS_TAB = "Interactions"
CUSTOMER_COLS = ["Customer ID", "Name", "Address", "Phone", "Date Added"]
INTERACTION_COLS = ["Customer ID", "Customer Name", "Date", "Type", "Content", "Logged At"]
INTERACTION_TYPES = ["Call", "Email", "Meeting", "Site Visit", "Text Message", "Other"]

# Column widths (pixels) applied when the app creates a tab, so the sheet is readable.
_CUSTOMER_WIDTHS = [110, 200, 320, 150, 110]
_INTERACTION_WIDTHS = [110, 200, 110, 110, 480, 160]


class SetupError(Exception):
    """A problem the user fixes on the Setup page (credentials, sharing, API access)."""


# --------------------------------------------------------------------------- config

def _migrate_old_settings() -> None:
    """Earlier versions kept config.json and the key next to the app; move copies to DATA_DIR."""
    if CONFIG_PATH.exists():
        return
    for name in ("config.json", DEFAULT_CREDENTIALS_FILE):
        old = APP_DIR / name
        if old.exists():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            (DATA_DIR / name).write_bytes(old.read_bytes())


def load_config() -> dict:
    try:
        _migrate_old_settings()
    except OSError:
        pass
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def credentials_path(cfg: dict) -> Path:
    path = Path(cfg.get("credentials_file") or DEFAULT_CREDENTIALS_FILE).expanduser()
    return path if path.is_absolute() else DATA_DIR / path


def validate_service_account(data: object) -> str:
    """Check a parsed key file and return the service account's email address."""
    if not isinstance(data, dict):
        raise SetupError("That file isn't a Google service-account key (expected a JSON object).")
    if data.get("type") != "service_account":
        if "installed" in data or "web" in data:
            raise SetupError(
                "That's an OAuth client file, not a service-account key. In Google Cloud go to "
                "IAM & Admin → Service Accounts → your account → Keys → Add key → JSON."
            )
        raise SetupError("That file isn't a Google service-account key (\"type\" should be \"service_account\").")
    for field in ("client_email", "private_key", "token_uri"):
        if not data.get(field):
            raise SetupError(f"The key file is missing \"{field}\". Download a fresh JSON key and try again.")
    return data["client_email"]


def read_service_account(path: Path) -> dict:
    if not path.exists():
        raise SetupError("No Google credentials yet. Upload your service-account key file on this page.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SetupError(f"Couldn't read {path.name}: {exc}") from exc
    validate_service_account(data)
    return data


def sheet_key_from(text: str) -> str | None:
    """Accept a full Google Sheets URL or a bare spreadsheet ID."""
    text = (text or "").strip()
    match = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", text)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{25,}", text):
        return text
    return None


# ------------------------------------------------------------------------ connection

def open_spreadsheet(creds_file: Path, sheet_key: str) -> gspread.Spreadsheet:
    """Authenticate, open the sheet and make sure both tabs exist. Raises SetupError."""
    info = read_service_account(creds_file)
    email = info["client_email"]
    project = info.get("project_id", "")
    not_shared = (
        f"The service account can't open that sheet. In Google Sheets click Share, add "
        f"{email} as an Editor, then click Connect again."
    )
    try:
        client = gspread.service_account(filename=str(creds_file))
        sheet = client.open_by_key(sheet_key)
        _ensure_tabs(sheet)
        return sheet
    except gspread.exceptions.SpreadsheetNotFound as exc:
        raise SetupError(
            "No spreadsheet found at that link. Check the URL, and make sure the sheet is shared with "
            f"{email} as an Editor."
        ) from exc
    except PermissionError as exc:  # gspread raises this for HTTP 403 on open
        raise SetupError(_explain_403(str(exc.__cause__ or exc), not_shared, project)) from exc
    except gspread.exceptions.APIError as exc:
        if exc.code == 403:
            raise SetupError(_explain_403(str(exc), not_shared, project, writing=True)) from exc
        if exc.code == 404:
            raise SetupError("No spreadsheet found at that link. Check the URL.") from exc
        raise SetupError(f"Google Sheets returned an error: {exc}") from exc
    except google_auth_errors.RefreshError as exc:
        raise SetupError(
            "Google rejected the credentials (the key may have been deleted or disabled). "
            f"Create a new JSON key for the service account and upload it. Details: {exc}"
        ) from exc
    except (google_auth_errors.TransportError, requests.exceptions.RequestException) as exc:
        raise SetupError(f"Couldn't reach Google. Check your internet connection. Details: {exc}") from exc


def _explain_403(detail: str, not_shared: str, project: str, writing: bool = False) -> str:
    if "SERVICE_DISABLED" in detail or "has not been used" in detail or "is disabled" in detail:
        link = "https://console.cloud.google.com/apis/library/sheets.googleapis.com"
        if project:
            link += f"?project={project}"
        return (
            f"The Google Sheets API is turned off for your Google Cloud project. Enable it here: {link} "
            "then wait a minute and click Connect again."
        )
    if writing:
        return not_shared.replace("can't open", "can view but not edit")
    return not_shared


def _ensure_tabs(sheet: gspread.Spreadsheet) -> None:
    worksheets = sheet.worksheets()
    existing = {ws.title: ws for ws in worksheets}
    specs = (
        (CUSTOMERS_TAB, CUSTOMER_COLS, _CUSTOMER_WIDTHS, "Phone"),
        (INTERACTIONS_TAB, INTERACTION_COLS, _INTERACTION_WIDTHS, "Content"),
    )
    for title, cols, widths, special_col in specs:
        ws = existing.get(title)
        if ws is None:
            # A brand-new spreadsheet has one empty tab ("Sheet1"); reuse it instead of leaving it behind.
            only_tab = worksheets[0] if len(worksheets) == 1 else None
            if (
                title == CUSTOMERS_TAB
                and only_tab is not None
                and INTERACTIONS_TAB not in existing
                and not any(any(cell.strip() for cell in row) for row in only_tab.get_all_values())
            ):
                only_tab.update_title(title)
                ws = only_tab
            else:
                ws = sheet.add_worksheet(title=title, rows=1000, cols=len(cols))
            _write_header(sheet, ws, cols, widths, special_col)
            continue
        header = [h.strip() for h in ws.row_values(1)]
        if not any(header):
            _write_header(sheet, ws, cols, widths, special_col)
            continue
        missing = [c for c in cols if c not in header]
        if missing:
            raise SetupError(
                f"The '{title}' tab is missing column(s): {', '.join(missing)}. Row 1 of that tab must "
                f"contain these headers: {', '.join(cols)}. Rename or delete the tab and the app will "
                "recreate it."
            )


def _write_header(sheet, ws, cols, widths, special_col) -> None:
    ws.update(range_name="A1", values=[cols], value_input_option="RAW")
    sid = ws.id
    col_idx = cols.index(special_col)
    col_range = {"sheetId": sid, "startRowIndex": 1, "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1}
    if special_col == "Phone":  # keep phone numbers as text so leading zeros and "+" survive
        special = {"repeatCell": {"range": col_range,
                                  "cell": {"userEnteredFormat": {"numberFormat": {"type": "TEXT"}}},
                                  "fields": "userEnteredFormat.numberFormat"}}
    else:  # wrap long interaction notes
        special = {"repeatCell": {"range": col_range,
                                  "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"}},
                                  "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)"}}
    requests_ = [
        {"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True},
                                           "backgroundColor": {"red": 0.91, "green": 0.94, "blue": 0.99}}},
            "fields": "userEnteredFormat(textFormat,backgroundColor)"}},
        {"updateSheetProperties": {
            "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount"}},
        special,
    ] + [
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
            "properties": {"pixelSize": w}, "fields": "pixelSize"}}
        for i, w in enumerate(widths)
    ]
    sheet.batch_update({"requests": requests_})


# ----------------------------------------------------------------------------- data

def _read_tab(ws: gspread.Worksheet, cols: list[str], with_rows: bool = False):
    """Read a tab into a DataFrame of strings, matching columns by header name.

    With with_rows=True, also returns the header and adds a "_row" column (sheet row number).
    """
    rows = ws.get_all_values()
    header = [h.strip() for h in rows[0]] if rows else []
    positions = {c: header.index(c) for c in cols if c in header}
    records = []
    for n, row in enumerate(rows[1:], start=2):
        rec = {c: (row[i].strip() if i < len(row) else "") for c, i in positions.items()}
        if any(rec.values()):
            rec["_row"] = n
            records.append(rec)
    df = pd.DataFrame(records, columns=cols + ["_row"]).fillna("")
    return (df, header) if with_rows else df.drop(columns="_row")


def parse_date(text: str) -> date | None:
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    try:
        return pd.to_datetime(text).date()
    except (ValueError, TypeError, OverflowError):
        return None


def clean_phone(raw: str) -> str:
    """Tidy US numbers to (301) 555-0123; leave anything else as typed."""
    raw = " ".join((raw or "").split())
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+") and not raw.startswith("+1"):
        return raw
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10 and "x" not in raw.lower():
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return raw


def phone_digits(text: str) -> str:
    digits = re.sub(r"\D", "", text or "")
    return digits[1:] if len(digits) == 11 and digits.startswith("1") else digits


def _next_customer_id(existing: pd.Series) -> str:
    nums = [int(m.group(1)) for v in existing if (m := re.fullmatch(r"[Cc](\d+)", str(v).strip()))]
    return f"C{max(nums, default=0) + 1:04d}"


class CRMStore:
    """Reads and writes the two CRM tabs."""

    def __init__(self, sheet: gspread.Spreadsheet):
        self.sheet = sheet

    @property
    def title(self) -> str:
        return self.sheet.title

    @property
    def url(self) -> str:
        return self.sheet.url

    def _tab(self, name: str) -> gspread.Worksheet:
        try:
            return self.sheet.worksheet(name)
        except gspread.exceptions.WorksheetNotFound:
            _ensure_tabs(self.sheet)
            return self.sheet.worksheet(name)

    # reads
    def customers(self) -> pd.DataFrame:
        """Read customers. Rows typed straight into the sheet get a Customer ID (and Date Added) here."""
        ws = self._tab(CUSTOMERS_TAB)
        df, header = _read_tab(ws, CUSTOMER_COLS, with_rows=True)
        needs_id = df.index[(df["Customer ID"] == "") & (df["Name"] != "")]
        if len(needs_id):
            id_col = header.index("Customer ID") + 1
            added_col = header.index("Date Added") + 1
            next_num = int(_next_customer_id(df["Customer ID"])[1:])
            updates = []
            for i in needs_id:
                new_id = f"C{next_num:04d}"
                next_num += 1
                df.at[i, "Customer ID"] = new_id
                updates.append({"range": rowcol_to_a1(df.at[i, "_row"], id_col), "values": [[new_id]]})
                if not df.at[i, "Date Added"]:
                    df.at[i, "Date Added"] = date.today().isoformat()
                    updates.append({"range": rowcol_to_a1(df.at[i, "_row"], added_col),
                                    "values": [[df.at[i, "Date Added"]]]})
            ws.batch_update(updates, value_input_option="RAW")
        return df.drop(columns="_row")

    def interactions(self) -> pd.DataFrame:
        df = _read_tab(self._tab(INTERACTIONS_TAB), INTERACTION_COLS)
        df["when"] = pd.to_datetime([parse_date(v) for v in df["Date"]])
        df["logged"] = pd.to_datetime(df["Logged At"], errors="coerce", format="mixed")
        return df

    # writes
    def add_customer(self, name: str, address: str, phone: str) -> dict:
        ws = self._tab(CUSTOMERS_TAB)
        current = _read_tab(ws, CUSTOMER_COLS)
        record = {
            "Customer ID": _next_customer_id(current["Customer ID"]),
            "Name": name,
            "Address": address,
            "Phone": phone,
            "Date Added": date.today().isoformat(),
        }
        self._append(ws, record)
        return record

    def add_interaction(self, customer_id: str, customer_name: str, when: date, kind: str, content: str) -> dict:
        record = {
            "Customer ID": customer_id,
            "Customer Name": customer_name,
            "Date": when.isoformat(),
            "Type": kind,
            "Content": content,
            "Logged At": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._append(self._tab(INTERACTIONS_TAB), record)
        return record

    @staticmethod
    def _append(ws: gspread.Worksheet, record: dict) -> None:
        # Write in the tab's own column order, in case someone rearranged the columns in Sheets.
        header = [h.strip() for h in ws.row_values(1)]
        row = [record.get(h, "") for h in header]
        ws.append_row(row, value_input_option="RAW", table_range="A1")
