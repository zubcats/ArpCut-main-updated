#!/usr/bin/env bash
# Set Cloudflare Worker secret CRASH_INGEST_TOKEN and print the matching GitHub secret value.
# Run on your PC (needs Cloudflare login). Does NOT print the token to shell history if you
# paste via wrangler interactively — this script can also pipe a generated value.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend/cloudflare-license-signin"

if [[ -n "${CRASH_INGEST_TOKEN:-}" ]]; then
  TOKEN="$CRASH_INGEST_TOKEN"
else
  TOKEN="$(openssl rand -hex 32)"
fi

echo "Setting Worker secret CRASH_INGEST_TOKEN…"
printf '%s' "$TOKEN" | npx wrangler secret put CRASH_INGEST_TOKEN

echo
echo "Deploying worker…"
npx wrangler deploy

echo
echo "Done. Add the SAME value as a GitHub Actions repository secret named CRASH_INGEST_TOKEN"
echo "(Settings → Secrets and variables → Actions), then rebuild experimental."
echo
echo "Token (copy once into GitHub; do not commit):"
echo "$TOKEN"
