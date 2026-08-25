# Deploying the Catalist DEMO (Vercel only — no backend)

A single, permanent public URL that shows the app off a **frozen snapshot** of
the current data — the AI Agent Intern job, its 2 candidates, their evaluations,
and their CV page images. There is **no backend, no database, no Render, no cold
start**. It's interactive within a browser session (shortlist, filter, "run
ingestion", "send") but resets on refresh, and simulated actions (ingestion /
email) are clearly labeled — nothing is fetched or sent.

> This is the demo build. For the full live deployment (Render backend + Supabase
> + Vercel), see [DEPLOY.md](DEPLOY.md) instead.

## What ships

- A Next.js frontend only. The data is bundled at build time
  (`frontend/src/demo-data/snapshot.json`) and the CV artifacts are static files
  under `frontend/public/media/candidates/…`.
- **No secrets** ship to the client — only three public `NEXT_PUBLIC_*` flags.
  There is no backend URL; every data path resolves locally to the snapshot and
  the static media.

## Steps (Vercel)

1. Vercel dashboard → **Add New… → Project** → import this GitHub repo.
2. **Root Directory:** `frontend`. Framework preset: **Next.js** (auto-detected).
3. **Environment Variables** (Project → Settings → Environment Variables) — add
   exactly these three, for all environments:

   | Key | Value | Meaning |
   | --- | --- | --- |
   | `NEXT_PUBLIC_DEMO_MODE` | `true` | Serve the bundled snapshot; disable all network calls |
   | `NEXT_PUBLIC_AUTH_ENABLED` | `true` | Keep the branded login screen (cosmetic in demo) |
   | `NEXT_PUBLIC_DEMO_PASSCODE` | *(your choice, e.g. `catalist`)* | The passcode the login screen checks, client-side |

   Do **not** set `NEXT_PUBLIC_API_BASE_URL` or any secret key — the demo needs none.

4. **Deploy.** Grab the URL — e.g. `https://catalist-demo.vercel.app`.
5. **Share the passcode** (`NEXT_PUBLIC_DEMO_PASSCODE`) with whoever opens the
   link — that's all they need. (If you leave the passcode blank, the login
   screen accepts anything.)

## What to expect

- The link is **permanent and reusable** — a static Vercel deployment, no
  database, **no cold start** (unlike the Render free tier).
- Opening the URL → the branded **/login** (with a small "Demo" badge) → enter
  the passcode → the Jobs landing with the overview strip and 3 jobs.
- The **AI Agent Intern** job opens to its 2 candidates with real scores, tiers,
  and the verdict track; a candidate detail shows the evidence-backed criteria
  **and** the actual CV page images.
- Shortlisting, tab filtering, and decisions update **in-session** (reset on
  refresh). "Run ingestion" and "Send assignment" run but show a **"Demo build —
  … simulated"** note; nothing is fetched or emailed.

## Notes / limits

- **Frozen snapshot.** To refresh the demo data, re-run the capture (see the
  Phase 14 commit / `frontend/src/demo-data/snapshot.json` + `public/media/`)
  against a live backend and redeploy.
- **Session-only mutations.** Every change is in-memory; a refresh restores the
  snapshot. This is intentional — it's a show-off build, not a live system.
- **The login gate is cosmetic** in demo mode (the data is a public snapshot,
  not sensitive live records). It exists so the branded login is part of the demo.
