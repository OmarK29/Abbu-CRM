# Simple CRM

A small customer tracker that runs on your computer and saves everything to a Google Sheet.

- **Customers**: add a customer (name, address, phone) and see the customer list.
- **Log Interaction**: pick a customer and record the date, type, and details of a call, email, meeting or visit.
- **Customer History**: one customer's contact card and every interaction as a timeline, newest first or oldest first. You can filter it by type or download it as a CSV file.

## What you need

- **Python 3.10 or newer.** Get it from https://www.python.org/downloads/. On Windows, tick **"Add python.exe to PATH"** during install.
- A Google account.

## Start the app

| Windows | Mac | Linux / any terminal |
|---|---|---|
| Double-click **`Start CRM (Windows).bat`** | Double-click **`Start CRM (Mac).command`**. The first time, macOS blocks it; see the note below. | `bash "Start CRM (Mac).command"` |

The first launch takes about a minute because it installs what the app needs into a `.venv` folder here. After that the app opens in your browser at http://localhost:8501. Keep the terminal window open while you use the app, and close it to stop the app.

Manual alternative: `pip install -r requirements.txt` then `streamlit run app.py`.

## Connect Google Sheets (one time, about 5 minutes)

The first time you open the app, the **Setup** page walks you through these steps:

1. **Create a Google Cloud project.** Go to https://console.cloud.google.com, open the project picker at the top, click **New project**, give it any name and click **Create**.
2. **Turn on the Google Sheets API.** Open https://console.cloud.google.com/apis/library/sheets.googleapis.com and click **Enable**. Check that your new project is selected at the top.
3. **Create a service account.** Go to **IAM & Admin → Service accounts → Create service account**, name it `crm` and click **Done**. You can skip the optional steps.
4. **Download a key.** Click the service account, then **Keys → Add key → Create new key → JSON**. A `.json` file downloads.
5. **Upload the key** on the app's Setup page. The app then shows the service account's email address, which looks like `crm@your-project.iam.gserviceaccount.com`.
6. **Share your sheet.** Create a blank sheet at https://sheets.new, click **Share**, add that email address as an **Editor**, and untick "Notify people".
7. **Paste the sheet's link** into the Setup page and click **Connect**.

The app creates the two tabs for you, with headers, the first time it connects. To use a different sheet later, go to **Settings** in the sidebar.

## How the sheet is laid out

**Customers** tab

| Customer ID | Name | Address | Phone | Date Added |
|---|---|---|---|---|
| C0001 | Jane Doe | 12 Oak St, Rockville, MD 20850 | (301) 555-0123 | 2026-09-22 |

**Interactions** tab

| Customer ID | Customer Name | Date | Type | Content | Logged At |
|---|---|---|---|---|---|
| C0001 | Jane Doe | 2026-09-22 | Call | Approved the quote; wants install before Oct 15. | 2026-09-22 14:05:11 |

**Customer ID** links the two tabs. Each interaction belongs to the customer with the same ID, so the history stays correct even if two customers share a name. Customer Name is copied into the Interactions tab only so the sheet is easy to read.

You can edit the sheet directly, for example to fix a typo or delete a row. After that, click **Refresh from sheet** in the app's sidebar, or wait about a minute. If you add a customer by hand in the sheet, give them a unique ID such as `C0042`.

## Files

| File | What it is |
|---|---|
| `app.py` | Starts the app, handles page navigation and the Google connection |
| `views.py` | The four pages |
| `sheets.py` | Reads and writes the Google Sheet |
| `config.json` | Created by Setup; stores the sheet link |
| `service_account.json` | Created by Setup; your Google key. **Keep it private**, because it gives access to any sheet shared with the service account. |

## Troubleshooting

- **"Python 3.10 or newer is required"**: install Python from python.org, then run the start file again. The Mac launcher skips older copies such as Anaconda's `(base)` Python and uses the newest Python it finds.
- **"The service account can't open that sheet"**: share the sheet with the service-account email as an **Editor**, not a Viewer.
- **"The Google Sheets API is turned off"**: click the link in the message, click **Enable**, wait a minute, and connect again.
- **Your organization blocks key creation** (the error mentions `iam.disableServiceAccountKeyCreation`): some work and school Google accounts don't allow keys. Use a personal Gmail account for the Google Cloud project. The sheet can still be shared from any account.
- **Mac says "Apple could not verify 'Start CRM (Mac).command'"**: click **Done**, open **System Settings → Privacy & Security**, scroll down to the message about *Start CRM (Mac).command*, and click **Open Anyway**. Enter your Mac password, then click **Open Anyway** again. You only need to do this once. The warning appears because the file was downloaded and isn't signed by an Apple-registered developer.
- **Port 8501 is busy**: the app is probably already running in another window. Close that window, or open http://localhost:8501.
