# Deploying Catalist (public demo)

A permanent public URL to show the app off:

- **Frontend (Next.js) → Vercel**
- **Backend (FastAPI) → Render** — a Docker web service (needs the `poppler`
  system binary for PDF→image, a persistent process, and a DB pool; none of
  which fit Vercel's serverless model — do **not** try to put the backend on
  Vercel).
- **Postgres → Supabase** and **email → Resend** are already remote.

> **Scope note — durable blob storage is deferred.** Candidate *records* (jobs,
> candidates, scores, statuses) live in Postgres and persist. Candidate CV *page
> images* are written to the container's local disk and are **lost on every
> redeploy / cold start**. That's accepted for this demo. Everything else works.

---

## 0. Prerequisites

- The repo is pushed to GitHub (Render and Vercel both deploy from it).
- You have these values handy:
  - **`DATABASE_URL`** — your Supabase connection string, the **same** one you
    use locally (so the existing data appears). Form:
    `postgresql+psycopg2://postgres:<password>@db.<ref>.supabase.co:5432/postgres`
    (or the Session-pooler host on an IPv4-only network — see the main README's
    Supabase section).
  - **`ANTHROPIC_API_KEY`** (`sk-ant-…`).
  - **`RESEND_API_KEY`** (`re_…`) and a **`RESEND_FROM_EMAIL`**.
  - **`GOOGLE_SERVICE_ACCOUNT_JSON`** — the *entire* service-account JSON key as
    a single string (only needed if you'll use live Google-Form intake). On
    Render there's no file to mount, so the app reads the raw JSON from this env
    var and materializes it to a temp file at runtime.
  - A **fresh** `APP_AUTH_PASSWORD` and a **fresh** `AUTH_SECRET_KEY` — see the
    security note below. Generate a secret with:
    ```bash
    python -c "import secrets; print(secrets.token_hex(32))"
    ```

> **Security — the app is now public.** Do **NOT** reuse your local
> `APP_AUTH_PASSWORD` / `AUTH_SECRET_KEY`. Set brand-new values on Render.

---

## A. Backend → Render

1. **New service.** Render dashboard → **New +** → **Web Service** → connect your
   GitHub repo. (Or **New +** → **Blueprint** to use the committed
   [`render.yaml`](render.yaml) — then skip to step 4 to fill in the secrets.)
2. **Runtime + root.**
   - **Language / Runtime:** **Docker**
   - **Root Directory:** `backend`
   - **Dockerfile Path:** `Dockerfile` (relative to the root directory)
   - **Plan:** Free
   - **Health Check Path:** `/health`
3. **Instance:** Free is fine for a demo (see the cold-start note at the end).
4. **Environment variables** (Render → your service → **Environment**). Add each
   — values are entered here, **never committed**:

   | Key | Value | Notes |
   | --- | --- | --- |
   | `STORE_BACKEND` | `postgres` | Use the shared Supabase DB |
   | `DATABASE_URL` | *(your Supabase URL)* | **Same as local** → existing data appears |
   | `EVALUATOR_MODE` | `anthropic` | Real AI scoring |
   | `ANTHROPIC_API_KEY` | *(sk-ant-…)* | |
   | `EMAIL_MODE` | `mock` | **Demo-safe** — no real emails (see below) |
   | `RESEND_API_KEY` | *(re-…)* | Needed only if `EMAIL_MODE=resend` |
   | `RESEND_FROM_EMAIL` | *(your sender)* | Needed only if `EMAIL_MODE=resend` |
   | `GOOGLE_SERVICE_ACCOUNT_JSON` | *(entire JSON string)* | Only if using Google intake |
   | `GOOGLE_SHEET_ID` | *(sheet id)* | Only if using a global sheet |
   | `APP_AUTH_USERNAME` | e.g. `admin` | |
   | `APP_AUTH_PASSWORD` | **fresh** strong value | Not your local one |
   | `AUTH_SECRET_KEY` | **fresh** 32-byte hex | Not your local one |
   | `AUTH_ENABLED` | `true` | Keep auth ON for a public URL |
   | `FRONTEND_ORIGIN` | *(leave blank for now)* | Set in step C to the Vercel URL |

   > **Preserve existing data (no migration).** Because `DATABASE_URL` +
   > `STORE_BACKEND=postgres` point at the **same Supabase project** you use
   > locally, the existing **AI Agent Intern** job and its **2 candidates**
   > (with their scores/statuses) show up on the live site immediately — they're
   > read straight from Postgres. Only the CV page **images** won't appear
   > (local-disk, deferred).

   > **Demo safety — `EMAIL_MODE=mock`.** With `mock`, "send assignment" writes
   > to a server-side outbox instead of emailing anyone — so a live demo can't
   > accidentally fire real email. If live email **is** part of your pitch, set
   > `EMAIL_MODE=resend` and provide `RESEND_API_KEY` + `RESEND_FROM_EMAIL`
   > (remember Resend only delivers to your own address until you verify a
   > domain — see the README).

5. **Create Web Service.** Render builds the Docker image (installs `poppler`,
   pip deps) and starts it. Watch the logs for `Application startup complete`.
   On first boot with the Postgres backend it runs `create_all()` (idempotent)
   and seeds sample jobs only if the table is empty.
6. **Grab the URL** — e.g. `https://catalist-backend.onrender.com`. Confirm
   `https://<render-url>/health` returns `{"status":"ok"}`.

---

## B. Frontend → Vercel

1. Vercel dashboard → **Add New… → Project** → import the same GitHub repo.
2. **Root Directory:** `frontend`. Framework preset: **Next.js** (auto).
3. **Environment Variables** (Project → Settings → Environment Variables):

   | Key | Value |
   | --- | --- |
   | `NEXT_PUBLIC_API_BASE_URL` | your Render URL, **no trailing slash** (e.g. `https://catalist-backend.onrender.com`) |
   | `NEXT_PUBLIC_AUTH_ENABLED` | `true` |

   No secret keys go in the frontend — only the public API base URL and the
   auth-enabled flag.
4. **Deploy.** Grab the URL — e.g. `https://catalist.vercel.app`.

---

## C. Wire CORS (back to Render)

The backend must allow the Vercel origin, or the browser blocks every call.

1. Render → backend service → **Environment** → set
   **`FRONTEND_ORIGIN`** = your exact Vercel URL (scheme + host, **no trailing
   slash**), e.g. `https://catalist.vercel.app`.
2. **Save** — Render redeploys automatically. (Auth is Bearer-token in the
   `Authorization` header, not cookies, so there's no cross-origin cookie
   "instant logout" trap; CORS just needs the exact origin allow-listed.)

---

## D. First-run checklist

1. **Warm the backend** (free tier sleeps — see below): open
   `https://<render-url>/health`, wait for `{"status":"ok"}`.
2. Open the **Vercel URL** → you should be redirected to **`/login`**.
3. **Log in** with `APP_AUTH_USERNAME` / the **fresh** `APP_AUTH_PASSWORD`.
4. On the **Jobs** landing, confirm the **AI Agent Intern** job appears with its
   **2 candidates** and their scores/statuses (served from the shared Supabase).
5. **Verify a flow:** open the pipeline → open a candidate → the AI evaluation +
   criteria render. Shortlist/decision changes persist (write to Postgres).
   (Sending an assignment writes to the outbox under `EMAIL_MODE=mock`.)
6. **No CORS errors / no instant logout** in the browser console.

If login "logs in then bounces back to /login": `FRONTEND_ORIGIN` doesn't exactly
match the Vercel origin (scheme/host/trailing-slash) — fix it in step C and
redeploy.

---

## Notes

- **Render free tier sleeps after ~15 min idle** (~30–60s cold start on the next
  request). **Hit the URL a minute before showing anyone** so it's warm.
- **Rotating the demo password:** change `APP_AUTH_PASSWORD` on Render and
  redeploy; existing sessions keep working until their token expires (12h).
- **Blob storage (deferred):** to make CV page images persist, move them to
  object storage (e.g. Supabase Storage / S3) and serve signed URLs — future
  work, intentionally out of scope here.

---

## Verify the image locally before deploying (optional but recommended)

```bash
cd backend
docker build -t catalist-backend .

# Run on a FREE port (8010 here), auth on, JSON store (no DB needed for a smoke test):
docker run --rm -p 8010:8010 \
  -e PORT=8010 \
  -e AUTH_ENABLED=true \
  -e APP_AUTH_USERNAME=admin \
  -e APP_AUTH_PASSWORD=localtest \
  -e AUTH_SECRET_KEY=$(python -c "import secrets;print(secrets.token_hex(32))") \
  catalist-backend

# In another shell:
curl -s localhost:8010/health                       # {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' localhost:8010/jobs   # 401 (no token)
TOKEN=$(curl -s -X POST localhost:8010/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"localtest"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" localhost:8010/jobs  # 200
```
