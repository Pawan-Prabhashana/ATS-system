# Catalist Recruit — Deploy Notes

Team-facing deployment of the Catalist screening ATS.

## Live URLs

| Surface | URL |
| --- | --- |
| **Frontend (team uses this)** | https://ats-system-lilac.vercel.app |
| **Backend API** | https://catalist-backend.onrender.com |
| Backend health | https://catalist-backend.onrender.com/health → `{"status":"ok"}` |

Log in with the `APP_AUTH_USERNAME` / `APP_AUTH_PASSWORD` set on Render.

## Architecture

- **Frontend** — Next.js on **Vercel** (root dir `frontend`). Static build; talks to the backend over HTTPS.
- **Backend** — FastAPI in a **Docker web service on Render** (root dir `backend`, Free instance, health check `/health`). poppler is in the image but unused at runtime (`CV_MODE=pdf_direct`).
- **Database** — **Supabase Postgres**, reached via the **Session Pooler** (IPv4). The direct `db.<ref>.supabase.co` host is IPv6-only and is NOT reachable from Render — always use the pooler string.
- **Intake** — one **Google Form / Sheet**; rows route to jobs by exact `role_key` match on the "Job you're applying for" column.
- **Scoring** — Anthropic (Claude) native PDF scoring (`CV_MODE=pdf_direct`, `EVALUATOR_MODE=anthropic`).

## Where each env var lives

### Render (backend service → Environment)
| Var | Notes |
| --- | --- |
| `STORE_BACKEND` | `postgres` |
| `DATABASE_URL` | **Supabase Session Pooler** URI (`...pooler.supabase.com:5432`). Secret. If the Supabase DB password is ever reset, update this. |
| `ANTHROPIC_API_KEY` | Secret. |
| `EVALUATOR_MODE` | `anthropic` |
| `CV_MODE` | `pdf_direct` |
| `EMAIL_MODE` | `mock` (email sending OFF — see limits) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Raw service-account JSON, one line. Secret. |
| `GOOGLE_SHEET_ID` | The single responses sheet id. |
| `FORM_ROLE_COLUMN` | `Job you're applying for` — the role question header (now matched tolerantly: case/whitespace/smart-quote-insensitive). |
| `APP_AUTH_USERNAME` / `APP_AUTH_PASSWORD` | Login creds. Password is secret. |
| `AUTH_SECRET_KEY` | Random 32-byte hex (`openssl rand -hex 32`). Secret. |
| `AUTH_ENABLED` | `true` |
| `FRONTEND_ORIGIN` | `https://ats-system-lilac.vercel.app` (exact origin, no trailing slash) — CORS allowlist. |

### Vercel (frontend project → Settings → Environment Variables)
| Var | Notes |
| --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | `https://catalist-backend.onrender.com` (no trailing slash) |
| `NEXT_PUBLIC_AUTH_ENABLED` | `true` |
| `NEXT_PUBLIC_DEMO_MODE` | **Must NOT be set** (or `false`). If `true`, the frontend serves a static demo snapshot and ignores the backend. |

## How to redeploy

Both services auto-deploy from GitHub `main` (`Pawan-Prabhashana/ATS-system`):

- **Push to `main`** → Render rebuilds the backend image and redeploys; Vercel rebuilds the frontend.
- **Backend env-var change** on Render → auto-redeploys.
- **Frontend env-var change** on Vercel → does NOT auto-redeploy; the `NEXT_PUBLIC_*` vars are baked in at build time, so trigger a manual **Redeploy** (Deployments → ⋯ → Redeploy, uncheck "Use existing Build Cache").

## Known limits (relay to the team)

1. **Email is OFF.** `EMAIL_MODE=mock` — no emails are actually sent, and the form has no email column yet. Shortlist/assignment "sends" are simulated only.
2. **Render Free sleeps.** After ~15 min idle the backend sleeps; the next request takes ~30–60s (cold start). **Warm it** (hit the URL / log in) a minute before showing anyone.

## Database note

The Postgres schema was brought current on first deploy (a clean-slate: `jobs` + `candidates` recreated with the current schema, then the 2 canonical jobs seeded — Backend Engineer, Graphic Design Intern; 0 candidates). Future schema changes are additive; the app runs `create_all` on startup (creates missing tables only — it does not add columns to existing tables).
