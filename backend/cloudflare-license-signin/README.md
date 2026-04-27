# Cloudflare Worker + KV (free tier) for ZubCut paid sign-in

## The idea in plain English

- You get a **normal HTTPS web address** from Cloudflare (your “license server”). Nothing runs on your home PC 24/7.
- **License Manager** sends each customer’s login data to that address when you create or change accounts.
- **ZubCut (paid)** uses the **same address** so customers can type **account + password** and receive their license.

You need a **free Cloudflare account** and **Node.js** installed (so the `npx` commands work).

---

## Simple checklist (do in this order)

### A. Turn on the license server (one time)

1. **Sign up / log in** at [cloudflare.com](https://www.cloudflare.com/) (free plan is fine).
2. On your PC, open a terminal in **this folder**: `backend/cloudflare-license-signin`.
3. Log Wrangler into Cloudflare:  
   `npx wrangler login`  
   (It opens the browser; approve access.)
4. Create storage for accounts:  
   `npx wrangler kv namespace create LICENSES`  
   Cloudflare prints an **id** that looks like a long hex string — **copy it**.
5. Open **`wrangler.toml`** in this folder. Replace `REPLACE_WITH_YOUR_KV_NAMESPACE_ID` with that **id**. Save the file.
6. Upload the code to Cloudflare:  
   `npx wrangler deploy`  
   When it finishes, note the **https://…workers.dev** URL it prints — that is your **Worker URL**. Save it somewhere.
7. Set a **private password** only you and License Manager will know (type it when prompted; nothing prints on screen):  
   `npx wrangler secret put ADMIN_SECRET`  
   Use a long random string (you can generate one in a password manager). **This is not** the customer’s password — it’s the **key between your License Manager and Cloudflare**.

### B. Connect License Manager to that server

1. Open **ZubCut License Manager** on your PC.
2. In **Cloud sign-in sync**, paste your **Worker URL** (the `https://…workers.dev` link from step A6).
3. Paste the **same** string you used for `ADMIN_SECRET` into **Admin secret**.
4. Turn on **push to cloud automatically**, click **Save cloud settings**, then **Test connection**. If the test fails, double-check the URL and secret.

### C. Put the same info into the ZubCut paid build

1. In **License Manager**, copy the line at the top: **Public Verify Key**.
2. In your ZubCut source, set **`PAID_LICENSE_PUBLIC_KEY_B64`** to that key (in `src/constants.py` or however you ship builds).
3. Set **`PAID_LICENSE_SIGNIN_URL`** to the **same Worker URL** you pasted in License Manager (or tell customers to set Windows env **`ZUBCUT_PAID_SIGNIN_URL`** to that URL).

After that, customers only need the **account name + password** you create in License Manager.

---

## What happens day to day

- **Create / renew / revoke / activate / delete** in License Manager updates the cloud (if auto-sync is on and B is set up).
- The Worker checks **expiry** and **active/revoked** when someone signs in, so dead accounts don’t get a license.

## License Manager (extra buttons)

- After **section B** is set up, **Create Account** / **Renew** / **Revoke** / **Activate** / **Delete** keep the cloud in sync when auto-push is on.
- **Push selected to cloud** — use if one account didn’t update on the server.
- **Export KV file (manual)** — only if you use Wrangler by hand instead of License Manager.

## ZubCut (customer app)

Same as **section C**: public verify key + Worker URL in the paid build. Customers use **Settings → “Paid: Sign in or change license…”**, or see a sign-in prompt at **first launch** if they don’t have a license file yet.

**`PAID_LICENSE_ENFORCEMENT`** is optional extra strictness for CI; normal releases use the public key + sign-in URL only.

## Admin API (used by License Manager)

- `POST /admin/upsert`  
  Body: `{ "secret": "<ADMIN_SECRET>", "account_key": "<lowercase user name>", "bundle": { ... } }`  
  Bundle fields: `password_salt`, `password_hash_hex`, `license` (signed payload + signature).
- `POST /admin/delete`  
  Body: `{ "secret": "<ADMIN_SECRET>", "account_key": "<lowercase user name>" }` — removes that KV key (used when you delete an account in License Manager).

## Limits

Cloudflare free tier has [limits](https://developers.cloudflare.com/workers/platform/limits/) on Workers and KV; suitable for modest user counts. Add rate limiting or WAF rules if you see abuse.
