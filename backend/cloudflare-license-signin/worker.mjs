/**
 * Free-tier license sign-in: Workers KV holds one JSON value per account (lowercase key).
 * Admin: POST /admin/upsert (secret + account_key + bundle), POST /admin/delete (secret + account_key).
 * Users: POST / with { account, password } — password verified with PBKDF2 (matches Python license_admin).
 * Server rejects expired or non-active licenses before returning the signed document.
 */

const SIGNIN_PBKDF2_ITERS_DEFAULT = 100000;
const SIGNIN_PBKDF2_ITERS_MAX = 100000;

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

export default {
  async fetch(request, env) {
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
      const accountKey = String(body?.account_key || '').trim().toLowerCase();
      const bundle = body?.bundle;
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
  },
};
