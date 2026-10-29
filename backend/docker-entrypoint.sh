#!/usr/bin/env sh
set -eu

: "${ADMIN_PASSWORD:?Set ADMIN_PASSWORD in .env}"
: "${DEVICE_TOKEN:?Set DEVICE_TOKEN in .env}"
# Seed is opt-in: restarting must not recreate records deleted by a teacher.
if [ "${SEED_ROSTER:-false}" = "true" ]; then
    python seed.py
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}"
