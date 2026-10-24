#!/bin/sh
# Production start (Dockerfile CMD, or a host's start command; run from services/api).
# 1. Apply migrations (idempotent: nothing to do when already at head).
# 2. Serve with exactly ONE worker: the review-submission rate limiter is in memory, per process,
#    so several workers would each allow the full limit (README "Known limitations").
# With ENVIRONMENT=production the app refuses to start on unsafe settings (a missing or short
# AUTH_SECRET_KEY, "*" in CORS_ALLOW_ORIGINS) and names the setting, never its value.
set -e
python -m alembic upgrade head
exec python -m uvicorn inkloom_api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
