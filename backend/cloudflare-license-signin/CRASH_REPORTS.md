# Crash reports API (Control Panel integration)

ZubCut stores crash reports on the **same Cloudflare Worker + KV** as license sign-in. After deploying an updated `worker.mjs`, use these endpoints from **ZubCut Control Panel** (or the `tools/crash_reports_admin.py` CLI on your PC).

## User flow (ZubCut app)

1. On an uncaught error, ZubCut assigns a short code (`ZC-XXXXXX`) and saves `%TEMP%\ZubCut-crash-ZC-XXXXXX.log`.
2. A dialog offers **Send report** (manual, default) or **Close**.
3. Optional setting `crash_report_auto_send` (default **off**) uploads automatically; failed uploads are retried on next launch.
4. Native hard crashes (access violations) cannot run Python afterward — only OS-level dumps apply.

## App endpoint

`POST /crash` — public ingest with optional shared secret + per-IP rate limit.

### Auth (recommended)

1. Set Worker secret: `npx wrangler secret put CRASH_INGEST_TOKEN` (or run `tools/set_crash_ingest_token.sh`).
2. Set the **same** value as GitHub Actions secret `CRASH_INGEST_TOKEN` so CI bakes it into ZubCut builds (`constants.CRASH_INGEST_TOKEN`).
3. Redeploy the worker, then rebuild experimental/main.

If `CRASH_INGEST_TOKEN` is **unset** on the Worker, `/crash` stays open (backward compatible).  
If it **is** set, the JSON body must include matching `ingest_token` (or `token`).

Runtime override on a PC: Windows env `ZUBCUT_CRASH_INGEST_TOKEN`.

Rate limit: about **30 reports per client IP per hour** (KV counter).

```json
{
  "ref": "ZC-ABC123",
  "body": "full traceback text…",
  "ingest_token": "<CRASH_INGEST_TOKEN when configured>",
  "time_utc": "2026-07-08T16:00:00+00:00",
  "platform": "Windows-10-…",
  "frozen": true,
  "build_commit": "35a1e27",
  "build_channel": "experimental",
  "build_time": "2026-07-08T12:00:00Z",
  "app_version": "1.2.3",
  "account_hint": "customer_username",
  "license_id": "uuid-from-license-payload",
  "exc_type": "RuntimeError",
  "exc_message": "Percent Cut failed to start",
  "zc_codes": [
    {"code": "ZC-NPCAP", "level": "fail", "source": "pc_readiness", "message": "Npcap missing…"}
  ],
  "zc_catalog": [
    {"code": "ZC-NPCAP", "message": "Npcap missing…"}
  ]
}
```

`zc_codes` are **diagnostic support codes** observed before the crash (readiness / `format_error_code`), not the random crash `ref`. `zc_catalog` is the full registry shipped with that build.

`log` is accepted as an alias for `body`. `licenseKey` / `account` are aliases for `account_hint`.

**Account linking:** ZubCut sends `account_hint` (sign-in account from `zubcut-license.json`) and `license_id` when the user is signed in. Unsigned sessions appear as empty / “not signed in” in Control Panel.

Response: `{ "ok": true, "ref": "ZC-ABC123", "message": "Crash report received." }`  
Unauthorized: `{ "ok": false, "error": "Unauthorized crash ingest." }` (HTTP 401)  
Rate limited: `{ "ok": false, "error": "Too many crash reports. Try again later." }` (HTTP 429)

## Admin endpoints (Control Panel / developer CLI)

All require JSON `secret` matching Worker `ADMIN_SECRET` (same as license upsert).

### List recent crashes

`POST /admin/crashes/list`

```json
{ "secret": "<ADMIN_SECRET>", "limit": 100 }
```

Response:

```json
{
  "ok": true,
  "total": 12,
  "crashes": [
    {
      "ref": "ZC-ABC123",
      "time_utc": "…",
      "received_at": "…",
      "platform": "…",
      "build_commit": "…",
      "build_channel": "experimental",
      "app_version": "…",
      "account_hint": "user",
      "exc_type": "RuntimeError",
      "exc_message": "…",
      "zc_codes": ["ZC-NPCAP", "ZC-WPA3"]
    }
  ]
}
```

List summaries store `zc_codes` as code strings; full `GET` reports keep objects + `zc_catalog`.

### Get full report

`POST /admin/crash/get`

```json
{ "secret": "<ADMIN_SECRET>", "ref": "ZC-ABC123" }
```

Returns `{ "ok": true, "report": { …, "body": "…" } }`.

### Delete report

`POST /admin/crash/delete`

```json
{ "secret": "<ADMIN_SECRET>", "ref": "ZC-ABC123" }
```

## KV layout

| Key | Value |
|-----|--------|
| `crash:ZC-XXXXXX` | Full JSON report (~48 KB body max) |
| `__crash_index__` | JSON array of summaries (newest first, max 500) |

## Developer CLI (this repo)

```bash
export ZUBCUT_LICENSE_SIGNIN_URL=https://zubcut-license-signin.zubcats.workers.dev
export ZUBCUT_ADMIN_SECRET='your-admin-secret'

python tools/crash_reports_admin.py list
python tools/crash_reports_admin.py get ZC-ABC123
python tools/crash_reports_admin.py get ZC-ABC123 --out crash.log
python tools/crash_reports_admin.py delete ZC-ABC123
```

## Control Panel UI (this repo)

Run the PyQt admin app:

```bash
python src/zubcut_control_panel.py
```

- **Accounts** tab — create / renew / revoke / activate / delete; cloud sign-in sync; push to cloud
- **Crash reports** tab — list, view full body, export, delete, filter by account, optional auto-refresh
- **Accounts** tab — **View crash reports** jumps to crashes filtered for that account
- **Install latest build** — downloads from the `control-panel-latest` release

## API reference (integrators)

## Deploy

After pulling worker changes:

```bash
cd backend/cloudflare-license-signin
npx wrangler deploy
```

To enable crash ingest auth (recommended):

```bash
# from repo root — generates a token, sets the Worker secret, deploys
tools/set_crash_ingest_token.sh
# then paste the printed token into GitHub Actions secret CRASH_INGEST_TOKEN and rebuild
```
