/**
 * Free-tier license sign-in: Workers KV holds one JSON value per account (lowercase key).
 * Admin: POST /admin/upsert (secret + account_key + bundle), POST /admin/delete (secret + account_key).
 * Users: POST / with { account, password } — password verified with PBKDF2 (matches Python license_admin).
 * Server rejects expired or non-active licenses before returning the signed document.
 *
 * Crash reports (ZubCut): POST /crash from the app; License Manager lists via POST /admin/crashes/list.
 * Stored under KV keys crash:<ref> with a rolling index at __crash_index__.
 */

const SIGNIN_PBKDF2_ITERS_DEFAULT = 100000;
const SIGNIN_PBKDF2_ITERS_MAX = 100000;
const CRASH_INDEX_KEY = '__crash_index__';
const CRASH_KV_PREFIX = 'crash:';
const CRASH_INDEX_MAX = 500;
const CRASH_BODY_MAX = 48000;

function jsonResponse(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS, GET',
      'Access-Control-Allow-Headers': 'Content-Type, Accept',
    },
  });
}

function b64ToArrayBuffer(s) {
  let t = String(s || '').replace(/\s/g, '');
  const pad = t.length % 4;
  if (pad) t += '='.repeat(4 - pad);
  const bin = atob(t);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

async function pbkdf2Sha256Hex(password, saltB64, iterations) {
  const iters = Math.max(1, Math.min(Number(iterations || SIGNIN_PBKDF2_ITERS_DEFAULT), SIGNIN_PBKDF2_ITERS_MAX));
  const salt = b64ToArrayBuffer(saltB64);
  const enc = new TextEncoder();
  const keyMaterial = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, [
    'deriveBits',
  ]);
  const bits = await crypto.subtle.deriveBits(
    {
      name: 'PBKDF2',
      hash: 'SHA-256',
      salt: new Uint8Array(salt),
      iterations: iters,
    },
    keyMaterial,
    256,
  );
  const bytes = new Uint8Array(bits);
  return [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
}

function timingSafeEqualHex(a, b) {
  const x = String(a || '').toLowerCase();
  const y = String(b || '').toLowerCase();
  if (x.length !== y.length) return false;
  let r = 0;
  for (let i = 0; i < x.length; i++) r |= x.charCodeAt(i) ^ y.charCodeAt(i);
  return r === 0;
}

async function sha256HexUtf8(s) {
  const buf = new TextEncoder().encode(String(s ?? ''));
  const hash = await crypto.subtle.digest('SHA-256', buf);
  return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

async function adminSecretOk(provided, expected) {
  if (!expected || typeof expected !== 'string') return false;
  const [a, b] = await Promise.all([sha256HexUtf8(provided), sha256HexUtf8(expected)]);
  return timingSafeEqualHex(a, b);
}

/** @returns {{ ok: true } | { ok: false, code: 'expired' | 'inactive' }} */
function licenseEligibleForLogin(license) {
  const p = license?.payload;
  if (!p || typeof p !== 'object') return { ok: false, code: 'inactive' };
  const st = String(p.status || '').trim().toLowerCase();
  if (st !== 'active') return { ok: false, code: 'inactive' };
  const raw = String(p.expires_at || '').trim();
  if (!raw) return { ok: false, code: 'inactive' };
  const t = Date.parse(raw);
  if (Number.isNaN(t)) return { ok: false, code: 'inactive' };
  if (Date.now() > t) return { ok: false, code: 'expired' };
  return { ok: true };
}

function pathnameKey(requestUrl) {
  try {
    const u = new URL(requestUrl);
    let p = u.pathname || '/';
    if (p.length > 1 && p.endsWith('/')) p = p.slice(0, -1);
    return p || '/';
  } catch {
    return '/';
  }
}

function normalizeCrashRef(ref) {
  const s = String(ref || '').trim().toUpperCase();
  if (!/^ZC-[0-9A-HJKLMNPQRSTUVWXYZ]{6}$/.test(s)) return '';
  return s;
}

function crashKvKey(ref) {
  return `${CRASH_KV_PREFIX}${ref}`;
}

async function readCrashIndex(kv) {
  try {
    const raw = await kv.get(CRASH_INDEX_KEY, { type: 'text' });
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

async function writeCrashIndex(kv, entries) {
  const trimmed = Array.isArray(entries) ? entries.slice(0, CRASH_INDEX_MAX) : [];
  await kv.put(CRASH_INDEX_KEY, JSON.stringify(trimmed));
}

async function storeCrashReport(kv, report) {
  const ref = normalizeCrashRef(report?.ref);
  if (!ref) return { ok: false, error: 'Invalid crash reference.' };
  const body = String(report?.body || report?.log || '');
  const accountHint = String(
    report?.account_hint || report?.licenseKey || report?.account || '',
  )
    .trim()
    .toLowerCase()
    .slice(0, 120);
  const licenseId = String(report?.license_id || report?.licenseId || '')
    .trim()
    .slice(0, 80);
  const payload = {
    ref,
    time_utc: String(report?.time_utc || new Date().toISOString()),
    platform: String(report?.platform || ''),
    frozen: Boolean(report?.frozen),
    build_commit: String(report?.build_commit || ''),
    build_channel: String(report?.build_channel || ''),
    build_time: String(report?.build_time || ''),
    app_version: String(report?.app_version || ''),
    account_hint: accountHint,
    license_id: licenseId,
    exc_type: String(report?.exc_type || '').slice(0, 120),
    exc_message: String(report?.exc_message || '').slice(0, 500),
    body: body.length > CRASH_BODY_MAX ? body.slice(0, CRASH_BODY_MAX) : body,
    received_at: new Date().toISOString(),
  };
  await kv.put(crashKvKey(ref), JSON.stringify(payload));
  const index = await readCrashIndex(kv);
  const summary = {
    ref,
    time_utc: payload.time_utc,
    platform: payload.platform,
    build_commit: payload.build_commit,
    build_channel: payload.build_channel,
    app_version: payload.app_version,
    account_hint: payload.account_hint,
    license_id: payload.license_id,
    exc_type: payload.exc_type,
    exc_message: payload.exc_message,
    received_at: payload.received_at,
  };
  const filtered = index.filter((e) => e && e.ref !== ref);
  filtered.unshift(summary);
  await writeCrashIndex(kv, filtered);
  return { ok: true, ref };
}

export default {
  async fetch(request, env) {
    try {
      if (request.method === 'OPTIONS') {
        return new Response(null, {
          status: 204,
          headers: {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST, OPTIONS, GET',
            'Access-Control-Allow-Headers': 'Content-Type, Accept',
          },
        });
      }

      const path = pathnameKey(request.url);
      const kv = env.LICENSES;

      if (request.method === 'GET') {
        if (path === '/admin/upsert' || path.startsWith('/admin/')) {
          return jsonResponse({ ok: false, error: 'Use POST.' }, 405);
        }
        return jsonResponse({ ok: true, service: 'zubcut-license-signin' });
      }

      if (request.method !== 'POST') {
        return jsonResponse({ ok: false, error: 'Use POST with JSON body.' }, 405);
      }

      let body;
      try {
        body = await request.json();
      } catch {
        return jsonResponse({ ok: false, error: 'Invalid JSON.' }, 400);
      }

      // --- Admin: push bundle from License Manager ---
      if (path === '/admin/upsert') {
        const expected = env.ADMIN_SECRET;
        const okSecret = await adminSecretOk(String(body?.secret ?? ''), expected);
        if (!okSecret) {
          return jsonResponse({ ok: false, error: 'Unauthorized.' }, 401);
        }
        if (!kv) {
          return jsonResponse({ ok: false, error: 'Server misconfigured (no KV).' }, 500);
        }
        const accountKey = String(body?.account_key || body?.account || body?.user_name || '')
          .trim()
          .toLowerCase();
        let bundle = body?.bundle || body?.kv_bundle || body?.record || null;
        if ((!bundle || typeof bundle !== 'object') && body && typeof body === 'object') {
          const maybeSalt = body?.password_salt;
          const maybeHex = body?.password_hash_hex;
          const maybeLic = body?.license;
          if (maybeSalt && maybeHex && maybeLic && typeof maybeLic === 'object') {
            bundle = {
              password_salt: maybeSalt,
              password_hash_hex: maybeHex,
              license: maybeLic,
              ...(body?.password_iters ? { password_iters: body.password_iters } : {}),
            };
          }
        }
        if (!accountKey || !bundle || typeof bundle !== 'object') {
          return jsonResponse({ ok: false, error: 'Missing account_key or bundle.' }, 400);
        }
        const salt = bundle?.password_salt;
        const hex = bundle?.password_hash_hex;
        const license = bundle?.license;
        if (!salt || !hex || !license || typeof license !== 'object') {
          return jsonResponse({ ok: false, error: 'Invalid bundle shape.' }, 400);
        }
        try {
          await kv.put(accountKey, JSON.stringify(bundle));
        } catch (e) {
          return jsonResponse({ ok: false, error: 'KV write failed.' }, 500);
        }
        return jsonResponse({ ok: true });
      }

      if (path === '/admin/delete') {
      const expected = env.ADMIN_SECRET;
      const okSecret = await adminSecretOk(String(body?.secret ?? ''), expected);
      if (!okSecret) {
        return jsonResponse({ ok: false, error: 'Unauthorized.' }, 401);
      }
      if (!kv) {
        return jsonResponse({ ok: false, error: 'Server misconfigured (no KV).' }, 500);
      }
      const accountKey = String(body?.account_key || '').trim().toLowerCase();
      if (!accountKey) {
        return jsonResponse({ ok: false, error: 'Missing account_key.' }, 400);
      }
      try {
        await kv.delete(accountKey);
      } catch (e) {
        return jsonResponse({ ok: false, error: 'KV delete failed.' }, 500);
      }
      return jsonResponse({ ok: true });
    }

      if (path === '/admin/crashes/list') {
        const expected = env.ADMIN_SECRET;
        const okSecret = await adminSecretOk(String(body?.secret ?? ''), expected);
        if (!okSecret) {
          return jsonResponse({ ok: false, error: 'Unauthorized.' }, 401);
        }
        if (!kv) {
          return jsonResponse({ ok: false, error: 'Server misconfigured (no KV).' }, 500);
        }
        const limit = Math.max(1, Math.min(Number(body?.limit || 100), CRASH_INDEX_MAX));
        const index = await readCrashIndex(kv);
        return jsonResponse({ ok: true, crashes: index.slice(0, limit), total: index.length });
      }

      if (path === '/admin/crash/get') {
        const expected = env.ADMIN_SECRET;
        const okSecret = await adminSecretOk(String(body?.secret ?? ''), expected);
        if (!okSecret) {
          return jsonResponse({ ok: false, error: 'Unauthorized.' }, 401);
        }
        if (!kv) {
          return jsonResponse({ ok: false, error: 'Server misconfigured (no KV).' }, 500);
        }
        const ref = normalizeCrashRef(body?.ref);
        if (!ref) {
          return jsonResponse({ ok: false, error: 'Missing or invalid ref.' }, 400);
        }
        const raw = await kv.get(crashKvKey(ref), { type: 'text' });
        if (!raw) {
          return jsonResponse({ ok: false, error: 'Crash report not found.' }, 404);
        }
        try {
          return jsonResponse({ ok: true, report: JSON.parse(raw) });
        } catch {
          return jsonResponse({ ok: false, error: 'Stored report is corrupt.' }, 500);
        }
      }

      if (path === '/admin/crash/delete') {
        const expected = env.ADMIN_SECRET;
        const okSecret = await adminSecretOk(String(body?.secret ?? ''), expected);
        if (!okSecret) {
          return jsonResponse({ ok: false, error: 'Unauthorized.' }, 401);
        }
        if (!kv) {
          return jsonResponse({ ok: false, error: 'Server misconfigured (no KV).' }, 500);
        }
        const ref = normalizeCrashRef(body?.ref);
        if (!ref) {
          return jsonResponse({ ok: false, error: 'Missing or invalid ref.' }, 400);
        }
        await kv.delete(crashKvKey(ref));
        const index = await readCrashIndex(kv);
        await writeCrashIndex(
          kv,
          index.filter((e) => e && e.ref !== ref),
        );
        return jsonResponse({ ok: true });
      }

      if (path === '/crash') {
        if (!kv) {
          return jsonResponse({ ok: false, error: 'Server misconfigured (no KV).' }, 500);
        }
        const result = await storeCrashReport(kv, body || {});
        if (!result.ok) {
          return jsonResponse(result, 400);
        }
        return jsonResponse({ ok: true, ref: result.ref, message: 'Crash report received.' });
      }

      if (path === '/validate') {
      const account = String(body?.account || '').trim().toLowerCase();
      const expectedLicenseId = String(body?.license_id || '').trim();
      if (!account) {
        return jsonResponse({ ok: false, error: 'Invalid account.' }, 400);
      }
      if (!kv) {
        return jsonResponse({ ok: false, error: 'Server misconfigured (no KV).' }, 500);
      }
      let raw;
      try {
        raw = await kv.get(account, { type: 'text' });
      } catch {
        return jsonResponse({ ok: false, error: 'Lookup failed.' }, 500);
      }
      if (!raw) {
        return jsonResponse({ ok: false, error: 'Account not found.' }, 404);
      }
      let record;
      try {
        record = JSON.parse(raw);
      } catch {
        return jsonResponse({ ok: false, error: 'Invalid account record.' }, 500);
      }
      const license = record?.license;
      if (!license || typeof license !== 'object') {
        return jsonResponse({ ok: false, error: 'Invalid account record.' }, 500);
      }
      const payload = license?.payload;
      const licenseId = String(payload?.license_id || '').trim();
      if (!payload || typeof payload !== 'object' || !licenseId) {
        return jsonResponse({ ok: false, error: 'Invalid account record.' }, 500);
      }
      if (expectedLicenseId && expectedLicenseId !== licenseId) {
        return jsonResponse({ ok: false, error: 'Session no longer valid.' }, 403);
      }
      const elig = licenseEligibleForLogin(license);
      if (!elig.ok) {
        const msg =
          elig.code === 'expired'
            ? 'This subscription has expired.'
            : 'This account is no longer active.';
        return jsonResponse({ ok: false, error: msg }, 403);
      }
      return jsonResponse({
        ok: true,
        account,
        license_id: licenseId,
        status: String(payload?.status || 'active'),
        expires_at: String(payload?.expires_at || ''),
      });
    }

      // --- User sign-in (default POST) ---
      const account = String(body?.account || '').trim().toLowerCase();
      const password = String(body?.password ?? '');

      if (!account || !password) {
        return jsonResponse({ ok: false, error: 'Invalid credentials.' }, 401);
      }

      if (!kv) {
        return jsonResponse({ ok: false, error: 'Server misconfigured (no KV).' }, 500);
      }

      let raw;
      try {
        raw = await kv.get(account, { type: 'text' });
      } catch {
        return jsonResponse({ ok: false, error: 'Lookup failed.' }, 500);
      }

      if (!raw) {
        return jsonResponse({ ok: false, error: 'Invalid credentials.' }, 401);
      }

      let record;
      try {
        record = JSON.parse(raw);
      } catch {
        return jsonResponse({ ok: false, error: 'Invalid credentials.' }, 401);
      }

      const salt = record?.password_salt;
      const expectedHex = record?.password_hash_hex;
      const iter = Number(record?.password_iters || record?.license?.payload?.password_iters || SIGNIN_PBKDF2_ITERS_DEFAULT);
      const license = record?.license;

      if (!salt || !expectedHex || !license || typeof license !== 'object') {
        return jsonResponse({ ok: false, error: 'Invalid credentials.' }, 401);
      }

      let derived;
      try {
        derived = await pbkdf2Sha256Hex(password, salt, iter);
      } catch {
        return jsonResponse({ ok: false, error: 'Invalid credentials.' }, 401);
      }

      if (!timingSafeEqualHex(derived, expectedHex)) {
        return jsonResponse({ ok: false, error: 'Invalid credentials.' }, 401);
      }

      const elig = licenseEligibleForLogin(license);
      if (!elig.ok) {
        const msg =
          elig.code === 'expired'
            ? 'This subscription has expired.'
            : 'This account is no longer active.';
        return jsonResponse({ ok: false, error: msg }, 403);
      }

      return jsonResponse({ ok: true, license });
    } catch (e) {
      return jsonResponse(
        { ok: false, error: `Unhandled server error: ${String(e?.message || e || 'unknown')}` },
        500,
      );
    }
  },
};
