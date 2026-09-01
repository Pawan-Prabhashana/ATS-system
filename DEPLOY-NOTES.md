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
| `INTAKE_MODE` | `google` — **required** to read the real Google Form. If unset it defaults to `local` (the offline fixture CSV) and ignores the sheet. |
| `STORE_BACKEND` | `postgres` |
| `DATABASE_URL` | **Supabase Session Pooler** URI (`...pooler.supabase.com:5432`). Secret. If the Supabase DB password is ever reset, update this. |
| `ANTHROPIC_API_KEY` | Secret. |
| `EVALUATOR_MODE` | `anthropic` |
| `CV_MODE` | `pdf_direct` |
| `EMAIL_MODE` | `mock` (email sending OFF — see limits) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Raw service-account JSON, one line. Secret. |
| `GOOGLE_SHEET_ID` | Responses spreadsheet id — current: `14IW96F-0ve9suM-b8jTH76aPcNSN_wb3Gm9nAHVC12s`. |
| `GOOGLE_SHEET_TAB` | `August 2025` — the worksheet/tab to read (the spreadsheet has one tab per hiring round). Unset = first tab. |
| `FORM_ROLE_COLUMN` | Optional. The role question header; matching is tolerant (case/whitespace/smart-quotes) and auto-detects "…applying for…" even if unset/wrong. |
| `APP_AUTH_USERNAME` / `APP_AUTH_PASSWORD` | Break-glass admin login (single account). Individual reviewer accounts live in the DB (see below). Password is secret. |
| `AUTH_SECRET_KEY` | Random 32-byte hex (`openssl rand -hex 32`). Secret. |
| `AUTH_ENABLED` | `true` |
| `FRONTEND_ORIGIN` | `https://ats-system-lilac.vercel.app` (exact origin, no trailing slash) — CORS allowlist. |

### Vercel (frontend project → Settings → Environment Variables)
| Var | Notes |
| --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | `https://catalist-backend.onrender.com` (no trailing slash) |
| `NEXT_PUBLIC_AUTH_ENABLED` | `true` |
| `NEXT_PUBLIC_DEMO_MODE` | **Must NOT be set** (or `false`). If `true`, the frontend serves a static demo snapshot and ignores the backend. |

## Reviewer accounts (individual logins)

Each reviewer has their own DB-backed login so the system attributes every
shortlist / reject / assignment to a person ("Shortlisted by Abdul"; full name
in the assignment email signature). Accounts: **mahima** (Mahima Passela),
**abdul** (Abdul Ashraff), **nidarshi** (Nidarshi Sivapadam), **pawan** (Pawan
Prabhashana). Passwords are stored hashed (pbkdf2); the plaintext was generated
once at provisioning and distributed out-of-band.

- Provision or reset: `STORE_BACKEND=postgres DATABASE_URL=<pooler> python -m scripts.provision_users` (prints new passwords once).
- The `APP_AUTH_USERNAME`/`APP_AUTH_PASSWORD` env admin still works as a fallback.
- Logins are concurrent-safe (stateless JWT; the token carries the display name).

## How to redeploy

Both services auto-deploy from GitHub `main` (`Pawan-Prabhashana/ATS-system`):

- **Push to `main`** → Render rebuilds the backend image and redeploys; Vercel rebuilds the frontend.
- **Backend env-var change** on Render → auto-redeploys.
- **Frontend env-var change** on Vercel → does NOT auto-redeploy; the `NEXT_PUBLIC_*` vars are baked in at build time, so trigger a manual **Redeploy** (Deployments → ⋯ → Redeploy, uncheck "Use existing Build Cache").

## Known limits (relay to the team)

1. **Email sending is OFF (but ready).** `EMAIL_MODE=mock` — the assignment email (Catalist Media template, chosen deadline, sender's name) is fully built and "sends" are simulated + attributed, but nothing actually goes out. The current form now HAS an email column, so to send for real: set `EMAIL_MODE=resend` with a verified Resend domain (`RESEND_API_KEY`, `RESEND_FROM_EMAIL`).
2. **Render Free sleeps.** After ~15 min idle the backend sleeps; the next request takes ~30–60s (cold start). **Warm it** (hit the URL / log in) a minute before showing anyone.

## Pulling, rescoring & auto-pull

- **Pull runs in the background with live progress.** "Pull applicants" starts a background job and the UI polls `GET /ingest/progress` to show "X of Y scored", so long pulls (hundreds of CVs) don't time out and the user sees it working. A pull is idempotent (dedup), so if it's interrupted, just pull again to finish the rest.
- **Rescore.** Change a job's rubric/description, then **Rescore** one candidate (candidate panel) or **Rescore all** (job page, background + progress). Rescoring replaces only the evaluation; status and human decisions are kept.
- **Auto-pull on job setup.** Creating a job kicks off a background pull automatically (when `INTAKE_MODE=google`), so applicants for that role start scoring without a manual pull.
- **Render Free caveat.** Background work only runs while the web instance is awake (it stays awake while actively pulling/being polled). The Free instance sleeps after ~15 min idle, so **continuous/scheduled auto-pull while nobody is using the app is not possible on Free** — it happens on job setup and on demand. For periodic auto-pull, upgrade to a paid Render tier (a cron/worker) or hit `POST /ingest/start` from an external scheduler.

## Database note

**Render's disk is ephemeral** — files written locally are wiped on every redeploy/restart. So the **assignment brief PDF is stored in Postgres** (`jobs.assignment_brief_data`) and materialized to a temp file at send time; the local copy is just a cache. ⚠️ Known same-class caveat: a **manually-added candidate's CV** is still stored on local disk only, so its PDF viewer/rescore can break after a restart (Google-pulled CVs are fine — they stream from Drive). Fixable the same way (store bytes in the DB) if manual adds become common.

**Team chat** persists to a `chat_messages` table (created automatically by `create_all` on boot — new *tables* are created, so no manual migration). The `/chat` page polls for new messages every 3s and shows full names.

The Postgres schema was brought current on first deploy (a clean-slate: `jobs` + `candidates` recreated with the current schema, then the 2 canonical jobs seeded — Backend Engineer, Graphic Design Intern; 0 candidates). Future schema changes are additive; the app runs `create_all` on startup (creates missing tables only — it does not add columns to existing tables).
