# Project Rules

## Git Integration
- **Always update GitHub**: At the end of every successful task or user request, stage all local modifications (respecting the `.gitignore`), commit them with a descriptive message, and push the branch to the remote repository on `main`.

## Architecture
- Single-file Flask monolith: `app.py` (~1600 lines) contains all routes, DB helpers, auth, and PDF generation. Templates live in `templates/`, static assets in `static/`.
- Entry point is `app.py`; `init_db()` runs on module import (idempotent schema creation + inline `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migrations). Do NOT expect separate migration files.
- PostgreSQL (Neon) via `DATABASE_URL` env var. The app raises `RuntimeError` if it is not set — every route/db helper depends on it. `SECRET_KEY` is optional (has insecure fallback).

## Run / Verify
- No tests, lint, or CI config exists. Verification is manual: set `DATABASE_URL`, then `python app.py` (runs with `debug=True`).
- `vercel.json` deploys `app.py` with `@vercel/python`; all routes are caught and proxied to Flask, so serverless `vercel dev`/deploy replaces a local WSGI server.

## Gotchas
- DB driver is `psycopg2`; `postgres://` URLs are rewritten to `postgresql://` in `get_db_connection()` — there is no other URL handling.
- Currency defaults to INR (₹); emoji icons (categories/payment methods) are defined in `DEFAULT_CATEGORY_ICONS` (`app.py`) and seeded per-user in `ensure_user_defaults`.