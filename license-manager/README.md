# ZubCut License Manager

Windows desktop admin app for ZubCut licensed builds:

- **Accounts** — create, renew, revoke, activate, delete; push to Cloudflare KV
- **Cloud sign-in sync** — Worker URL, admin secret, auto-push, connection test
- **Crash reports** — list, view, export, and delete reports sent from ZubCut

Uses the same Cloudflare Worker as `backend/cloudflare-license-signin/`.

## Run from source

```bash
cd license-manager
python -m venv venv
# Windows: venv\Scripts\activate
source venv/bin/activate
pip install -r requirements.txt
python run.py
```

## First-time setup

1. Generate an Ed25519 private key (PEM) for signing licenses, or reuse your existing key.
2. In the app, browse to the `.pem` file — copy **Public Verify Key** into ZubCut builds (`LICENSE_PUBLIC_KEY_B64`).
3. Open the **Cloud sign-in sync** tab: paste your Worker URL and `ADMIN_SECRET`, save, and test connection.
4. Create accounts on the **Accounts** tab; enable auto-push or use **Push selected to cloud**.

## Crash reports tab

After the worker is deployed with crash endpoints (`npx wrangler deploy` in `backend/cloudflare-license-signin/`):

1. Configure cloud settings (same URL + admin secret as license sync).
2. Open **Crash reports** → **Refresh**.
3. Select a row to see summary; double-click or **View full report** for the traceback body.
4. **Export body…** saves a `.log` file; **Delete report** removes it from KV.
5. **Auto-refresh** polls every 60 seconds.

Customers send reports from the ZubCut crash dialog (**Send report**).

## Data files

| Platform | Path |
|----------|------|
| Windows | `%APPDATA%\ZubCut-LicenseManager\settings.json` |
| Linux/macOS (dev) | `~/.config/ZubCut-LicenseManager/settings.json` |

Accounts are stored beside settings in `accounts.json` (password hashes only — not plaintext passwords).

## API reference

See `backend/cloudflare-license-signin/CRASH_REPORTS.md` and `README.md`.
