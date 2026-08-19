# Catalist Recruit Screening

Internal recruitment-screening tool. Candidates apply via a Google Form (CV
upload); the system parses each CV, evaluates it against a job description + a
scoring rubric using a vision+text LLM, ranks candidates, lets a human
review/override and confirm a shortlist, then emails an assignment to
shortlisted candidates and tracks status.

This repository currently implements **Phases 1–5 of 6** plus an evaluation
refinement: the scaffold + CV parsing core (Phase 1), real vision+text
evaluators behind one interface (Phase 2 — OpenRouter, plus a native Anthropic
evaluator and conditional vision added in a later refinement), candidate intake
+ an ingestion pipeline + a candidate store (Phase 3), a **review dashboard with
a human shortlist/reject approval gate** (Phase 4), and a **multi-job
architecture** (Phase 5) — every candidate is scoped to a `Job` (its own JD +
rubric), ingestion and the candidate views are job-scoped and isolated, plus a
retained assignment-email capability. It runs **fully offline by default**
(`EVALUATOR_MODE=mock`, `INTAKE_MODE=local`, `EMAIL_MODE=mock`) — the real
evaluators, Google intake, and Resend email are opt-in, and the test suite never
makes a live call. See
[OpenRouter / going live](#openrouter--going-live),
[Anthropic / going live](#anthropic--going-live), and
[Google intake / going live](#google-intake--going-live).

---

## What Phase 1 delivers

- A monorepo scaffold (`backend/` + `frontend/`).
- A **parsing pipeline** that turns a PDF into a structured `ParsedCV`:
  - full text + per-page text via **pdfplumber**;
  - one **PNG per page** via **pdf2image** (poppler), saved under a
    per-candidate output directory, with paths + dimensions recorded;
  - a `text_extraction_quality` flag (`ok` / `low`) — `low` means very little
    text was recovered, i.e. a likely scanned/image-only CV that the later
    vision step should read from the images;
  - metadata: page count, filename, SHA-256 file hash (for dedup later).
- **Pydantic v2 data models** that later phases depend on.
- An **evaluator interface** (`Evaluator` protocol) plus a deterministic
  **mock** implementation — no LLM, no API keys — so the whole flow runs
  without network access.
- A FastAPI endpoint **`POST /parse`** that accepts a PDF upload and returns the
  `ParsedCV` as JSON.
- A **CLI** that parses a CV, runs the mock evaluator, and prints the result.
- **Sample data**: a text-based CV, a scanned-style (image-only) CV, a job
  description, and a rubric.
- **Tests** (pytest).

## What Phase 2 adds

- **`OpenRouterEvaluator`** (`app/evaluation/real.py`) — a real vision+text
  evaluator implementing the same `Evaluator` protocol, calling OpenRouter's
  OpenAI-compatible chat completions endpoint via `httpx`. Multimodal message
  = system prompt (rubric + weights + scoring rules) + extracted text + up to
  `MAX_EVAL_PAGES` page images (downscaled/JPEG-compressed). Strict-JSON output
  parsed into `Evaluation`, with a one-shot corrective retry, network
  retry-on-timeout/5xx, and typed errors.
- **`get_evaluator()`** factory (`app/evaluation/factory.py`) selecting
  `mock` / `openrouter` / `anthropic` from `EVALUATOR_MODE`; `cli.py` calls it
  instead of a concrete class.
- **Prompt artifact** (`app/evaluation/prompts.py`) and **image prep**
  (`app/evaluation/images.py`) as separate, iterable modules.
- **Offline tests** (`respx`) covering the happy path, JSON retry, twice-bad →
  `EvaluationError`, missing-key → `EvaluatorConfigError`, factory selection,
  and image sizing.

## What Phase 3 adds

- **Intake sources** (`app/intake/`) behind an `IntakeSource` protocol +
  `get_intake_source()` factory (`INTAKE_MODE`):
  - `LocalFixtureIntakeSource` — offline, reads `sample_data/mock_form_responses.csv`
    and copies the bundled sample CVs (3 distinct candidates).
  - `GoogleFormsIntakeSource` — reads the linked response Sheet (Sheets API v4)
    and downloads each CV from Drive (Drive API v3). Credentials/clients are
    built **lazily inside the methods**: importing the module and constructing
    the class need no env vars or even the Google libraries; misconfiguration
    raises `IntakeConfigError` only when a method is called.
- **Candidate store** (`app/store/`) behind a `CandidateRepository` protocol +
  `get_candidate_store()` factory: `JSONCandidateStore` (single JSON file,
  atomic temp-file + rename writes). Deliberately a placeholder for the Phase 6
  Supabase store — swapping touches only `json_store.py` + the factory.
- **Ingestion pipeline** (`app/pipeline/ingest.py`) — `run_ingestion()`:
  intake → download → `parse_cv_file` → **dedup by `file_hash`** (skip if seen)
  → evaluate (mock/real) → store, with per-candidate error isolation (one bad
  CV never aborts the batch). Returns an `IngestionSummary`.
- **API** (additive): `POST /ingest` runs the pipeline; `GET /candidates` lists
  stored records ranked by `overall_score` — this is where evaluation output
  becomes visible over HTTP.
- **CLI**: `python -m app.cli ingest` runs the pipeline and prints the summary +
  a ranked candidate list.
- **Offline tests** covering 3-in end-to-end, second-run all-skipped (dedup),
  one-corrupt-among-valid, Google constructible-but-raises-on-call, factory
  selection, store atomicity/ordering, and the two endpoints.

## What Phase 4 adds

- **Stable artifact persistence** — ingestion now copies each candidate's CV +
  rendered page images into `data/candidates/<id>/` (`cv.pdf`, `page_1.png`, …).
  `CandidateRecord` gained `artifact_dir` / `cv_file` / `page_image_files`.
- **Review endpoints** — `GET /candidates/{id}` (full detail + media URLs, 404
  if missing), `PATCH /candidates/{id}/decision` (the approval gate: records a
  `shortlist`/`reject` + optional note + timestamp; 400 invalid, 404 missing).
  `Candidate` gained `reviewer_note` / `decided_at` (both optional, additive).
- **Static media** — `data/candidates/` is served at `/media/candidates` so the
  frontend loads page images + the original CV by URL. CORS allows the dev
  frontend origin.
- **Store** — `CandidateRepository` gained `get(id)` and `update_decision(...)`
  (atomic writes, as before).
- **Frontend review dashboard** (Next.js + TS + Tailwind): a score-ranked list
  and a per-candidate detail view (rendered CV pages, per-criterion score +
  weight + evidence, prominent overall score/recommendation) with a
  confirm-with-note Shortlist/Reject gate that can be re-decided.
- **Backend tests** for artifact persistence, detail 200/404, decision
  success/400/404, and decision round-tripping through the store.

The approval gate only records the human decision.

## What Phase 5 adds — multi-job architecture

Screening is now scoped to **jobs**: each `Job` carries its own job description +
rubric, and candidates belong to exactly one job.

- **`Job` model + `JobRepository`** — `Job` (id, title, job_description, embedded
  `Rubric`, status `open|closed`, created_at); `JSONJobRepository` backed by
  `data/jobs.json` (same atomic-write pattern), `get_job_repository()` factory.
- **Job scoping on candidates** — `Candidate` gained `job_id` (additive). The old
  `data/candidates.json` has no `job_id`, so **reset it when this lands** (see
  [Reset candidate data](#reset-candidate-data)).
- **Job-scoped ingestion** — `POST /jobs/{job_id}/ingest` pulls the job's JD +
  rubric, filters intake to that job, and tags the resulting candidates with
  `job_id`. The old global `POST /ingest` is **removed**. Local-fixture intake
  filters by a new `job_id` CSV column; Google-forms intake gained a `job_id`
  parameter that is **forward-looking only** (real per-form mapping is later).
- **Categorized/filtered views** — `GET /jobs/{job_id}/candidates?tier=&status=`
  (tier = `Evaluation.recommendation`, status = `CandidateStatus`, combinable,
  ranked by score) and `GET /jobs/{job_id}/summary` (counts by tier and by
  status). `GET /jobs`, `POST /jobs`, `GET /jobs/{id}` manage jobs.
  `GET /candidates/{id}` now joins `job_id` + `job_title`.
- **Seeding** — two sample jobs (**Backend Engineer** using `rubric.json`,
  **Graphic Designer** using `rubric_design.json`) are declared in
  `sample_data/jobs_seed.json` and applied by `seed_jobs()` (CLI `seed-jobs`, or
  auto-seeded on server start when the job store is empty).
- **Tests** — job CRUD + repository atomicity, seeding idempotency, **job
  isolation** (job A's ingest never appears under job B), every tier/status
  filter combination, and summary counts matching the data.

## Assignment email dispatch (retained capability)

- **Email dispatch** (`app/email/`) behind an `EmailSender` protocol +
  `get_email_sender()` factory (`EMAIL_MODE`):
  - `MockEmailSender` (default, offline) — writes each message to
    `data/outbox/<candidate_id>_<timestamp>.json` instead of sending.
  - `ResendEmailSender` — real send via the Resend API (plain `httpx` POST, no
    extra SDK). Lazy creds; runtime failures come back as
    `EmailSendResult(success=False, ...)` rather than raising. See
    [Assignment email / going live](#assignment-email--going-live).
- **Assignment template** (`app/email/templates.py`) — subject + HTML body with
  the candidate's name, role, and a clearly-stated deadline, plus the
  `sample_data/assignment_brief.pdf` attachment.
- **Endpoint** — `POST /candidates/{id}/send-assignment` (the gated action):
  404 missing; **409** if the candidate isn't `shortlisted` (a second send on an
  already-`assignment_sent` candidate is blocked unless `force: true`, which
  logs a distinct resend via `assignment_sent_count`); **502** on send failure
  with the status left unchanged so the reviewer can retry; on success sets
  status `assignment_sent` + `assignment_sent_at` + `assignment_deadline`.
- **Model/store** — `Candidate` gained `assignment_sent_at` /
  `assignment_deadline` / `assignment_sent_count` (additive); the repository
  gained `record_assignment_sent(...)` (atomic).
- **Frontend** — a **Send Assignment** action (confirm step) shown only when
  `shortlisted`; once sent, an **Assignment Sent** panel with date + deadline and
  a **Resend** (`force`) option showing the send count; a 502 is surfaced and
  left retryable.
- **Backend tests** — mock outbox happy path + deadline math, 409s, `force`
  resend/count, injected-failing-sender 502, and Resend config-error-at-call-time.

### Explicitly *not* in Phase 5 (multi-job)
No frontend changes (the dashboard is still single-list and its "Run ingestion"
button targets the removed global endpoint — Phase 7 reworks it), no real
multi-sheet Google Forms config (interface stub only). And across the build so
far: no live API calls in tests/CI, no auth/login.

## What Phase 6 adds — bulk assignment send

- **Shared send service** (`app/pipeline/assignment.py`) — the per-candidate
  send flow (status/force gating, sender call, result handling, repository
  update) was lifted out of the route into `send_assignment_to_candidate(...) ->
  SendOutcome`. `POST /candidates/{id}/send-assignment` is now a thin wrapper
  translating the outcome into the same 404/409/500/502/200 behavior as before
  (the unchanged Phase 5 email tests prove it).
- **`POST /jobs/{job_id}/send-assignments`** — bulk send (see
  [Bulk send](#bulk-send)). Sequential (deliberately, for provider rate-limit
  safety); one candidate's failure never aborts the batch.
- **Store** — `CandidateRepository.list_by_job(job_id, status=None)`.
- **Tests** — mixed partition (sent/skipped/failed), explicit ids incl. a
  wrong-job candidate (excluded, not processed), injected always-fail sender
  (failures isolated, others still advance), `force` resend + count, zero
  eligible → `requested_count: 0` (not an error), unknown job → 404.

### Explicitly *not* in Phase 6
No frontend (Phase 7), no Supabase (Phase 8), no concurrency/parallel sending,
no per-send retry/backoff within a bulk call (a failed send just lands in
`failed`; re-trigger later — the retryable-state pattern).

---

## Architecture

```
backend/app/
  models/        Pydantic models — the cross-phase data contract
  parsing/       text_extractor (pdfplumber) + image_renderer (pdf2image)
                 + orchestrator (parse_cv_bytes / parse_cv_file)
  evaluation/    base.Evaluator (Protocol) + factory.get_evaluator()
                 mock.MockEvaluator (offline) + real.OpenRouterEvaluator
                 anthropic_native.AnthropicEvaluator (native SDK)
                 prompts.py (conditional visual prompt) + images.py (resize/encode)
                 _response.py (shared JSON parse) + errors.py (typed errors)
  intake/        base.IntakeSource (Protocol) + factory.get_intake_source()
                 local_fixture.py (CSV) + google_forms.py (Sheets + Drive)
                 errors.py (IntakeConfigError)
  store/         base.{CandidateRepository, JobRepository} (Protocols)
                 json_store.JSONCandidateStore + job_store.JSONJobRepository
                 seed.py (jobs_seed.json) + factory.{get_candidate_store,
                 get_job_repository}
  email/         base.EmailSender (Protocol) + factory.get_email_sender()
                 mock_sender.py (outbox) + resend_sender.py (Resend via httpx)
                 templates.py (assignment email) + errors.py (EmailConfigError)
  pipeline/      ingest.run_ingestion(job_id=…) + IngestionSummary; context
  api/routes.py  /parse, /jobs/…, /candidates[/{id}[/decision|/send-assignment]]
  config.py      thresholds, dirs, DPI, evaluator/intake/store/email settings
  cli.py         python -m app.cli <pdf> | seed-jobs | ingest <job_id>
  main.py        FastAPI app factory (+ CORS, /media mount, job auto-seed)
  scripts/       generate_samples.py (dev-only sample PDF generator)
  sample_data/   sample CVs + rubric[_design].json + jobs_seed.json
                 + mock_form_responses.csv (job_id column) + assignment_brief.pdf
  data/          candidates.json + jobs.json + candidates/<id>/ + outbox/ (ignored)
  tests/
frontend/        Next.js + TS + Tailwind review dashboard
```

Data flow:

```
PDF bytes
  └─ orchestrator.parse_cv_bytes()
       ├─ validate (%PDF- header) ──► clean ValueError on bad input
       ├─ text_extractor.extract_text()   (pdfplumber)
       ├─ image_renderer.render_pages()   (pdf2image → PNGs on disk)
       ├─ quality flag (len(text) < threshold ? "low" : "ok")
       └─► (Candidate, ParsedCV)
              └─ Evaluator.evaluate(parsed_cv, job_description, rubric) → Evaluation
```

### The evaluator seam (Phase 1 mock, Phase 2 real)
Every evaluator implements one interface —

```python
# app/evaluation/base.py
class Evaluator(Protocol):
    name: str
    def evaluate(self, parsed_cv: ParsedCV,
                 job_description: str, rubric: Rubric) -> Evaluation: ...
```

Three implementations exist, chosen at runtime by `get_evaluator()`
(`app/evaluation/factory.py`) via the `EVALUATOR_MODE` env var:

- **`MockEvaluator`** (`mock`, default) — deterministic, offline, no API key.
- **`OpenRouterEvaluator`** (`openrouter`) — vision+text scoring via OpenRouter's
  OpenAI-compatible API (`app/evaluation/real.py`). See
  [OpenRouter / going live](#openrouter--going-live).
- **`AnthropicEvaluator`** (`anthropic`) — vision+text scoring via Anthropic's
  native SDK (`app/evaluation/anthropic_native.py`). See
  [Anthropic / going live](#anthropic--going-live).

Both real evaluators send the extracted `raw_text`; **page images are attached
only when the rubric's `requires_visual_review` is `true`** (capped at the first
`MAX_EVAL_PAGES` pages, downscaled + JPEG-compressed). For a content-only rubric
(`false`, the default) the request is text-only — no image payload, no
visual-hierarchy scoring — which is the real cost/latency saving. See
[Conditional vision](#conditional-vision-requires_visual_review).

Call sites use `get_evaluator()` (never a concrete class), so switching modes is
a pure env change with no code edits. The two real evaluators share the same
prompts (`prompts.py`) and response parsing (`_response.py`); only the message
shape + SDK differ. Data models already reserve room for later phases:
`Candidate.status` includes `shortlisted | assignment_sent | submitted |
rejected`, and `Candidate.source_form_row` is there for the Google Form
integration.

**Provider swappability.** Each provider's specifics live in exactly one file
(`real.py` for OpenRouter, `anthropic_native.py` for Anthropic). Switching an
OpenRouter model (e.g. `openai/gpt-4o`) is just `OPENROUTER_MODEL`; switching a
Claude model is just `ANTHROPIC_MODEL`. The interface, prompts, image prep
(`images.py`), and all callers are untouched.

---

## Setup

### 1. System dependency: poppler

`pdf2image` renders PDF pages to images using **poppler**. Install the system
package first:

| OS | Command |
| --- | --- |
| macOS (Homebrew) | `brew install poppler` |
| Debian / Ubuntu | `sudo apt-get install poppler-utils` |
| Fedora | `sudo dnf install poppler-utils` |
| Windows | Install poppler and add its `bin/` to `PATH` |

Verify: `pdftoppm -v` should print a version. Without poppler, text extraction
still works but page-image rendering is skipped and a warning is recorded in
`parser_warnings`.

### 2. Python environment

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. (Optional) regenerate the sample PDFs

The sample CVs are committed, but you can regenerate them:

```bash
python scripts/generate_samples.py
```

---

## Running

All commands below are run from `backend/` with the venv activated.

### CLI

```bash
python -m app.cli sample_data/sample_cv_text.pdf
```

Prints a JSON object with `parsed_cv` and (mock) `evaluation`. The text-based
sample yields non-empty text and one page image per page written under
`backend/output/<candidate_id>/pages/`. The scanned-style sample:

```bash
python -m app.cli sample_data/sample_cv_scanned.pdf
```

reports `"text_extraction_quality": "low"`.

Optional flags: `--rubric <path.json>` and `--jd <path.txt>` (default to the
bundled sample data).

### API

```bash
uvicorn app.main:app --reload
```

Then upload a PDF to `POST /parse`:

```bash
curl -F "file=@sample_data/sample_cv_text.pdf" http://127.0.0.1:8000/parse
```

Returns the `ParsedCV` as JSON. A non-PDF / corrupt / empty upload returns a
clean **400** with a message (no stack trace). Interactive docs at
`http://127.0.0.1:8000/docs`. Health check: `GET /health`.

**Endpoints:**

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness check |
| `POST` | `/parse` | Parse an uploaded PDF → `ParsedCV` |
| `GET` | `/jobs` | List jobs |
| `POST` | `/jobs` | Create a job → 201; 409 on duplicate id |
| `GET` | `/jobs/{id}` | Job detail; 404 if missing |
| `POST` | `/jobs/{id}/ingest` | Ingest that job's submissions → `IngestionSummary`; 404 if missing |
| `GET` | `/jobs/{id}/candidates?tier=&status=` | Job's candidates, filtered + ranked; 404 if missing |
| `GET` | `/jobs/{id}/summary` | Counts by tier + by status for the job; 404 if missing |
| `GET` | `/candidates` | List all stored candidates (across jobs), ranked by score |
| `GET` | `/candidates/{id}` | Candidate detail (evaluation + media URLs + job context); 404 |
| `PATCH` | `/candidates/{id}/decision` | Record `shortlist`/`reject` + note; 400 invalid, 404 missing |
| `POST` | `/candidates/{id}/send-assignment` | Send the assignment email (gated on `shortlisted`); 404, 409, 502 |
| `POST` | `/jobs/{id}/send-assignments` | Bulk-send to the job's shortlisted (or an explicit id list) → `BulkSendResult`; 404 if job missing |
| `GET` | `/media/candidates/{id}/...` | Static per-candidate artifacts (`cv.pdf`, `page_N.png`) |

The global `POST /ingest` from earlier phases was **removed** in favour of the
job-scoped `POST /jobs/{id}/ingest`.

`/media/candidates` is a `StaticFiles` mount over `data/candidates/`, so the
frontend loads CV page images and the original PDF directly by URL.

### Tests

```bash
pytest
```

Covers: the text CV extracts non-empty text + the expected number of page
images (written to disk); the scanned CV is flagged `low`; bad input raises a
clean error; and the mock evaluator returns a schema-valid, deterministic
`Evaluation`.

---

## Configuration

Environment variables (see `app/config.py`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `CATALIST_OUTPUT_DIR` | `backend/output` | Where per-candidate PDFs + page PNGs are written |
| `CATALIST_LOW_TEXT_THRESHOLD` | `100` | Below this many extracted characters → `low` |
| `CATALIST_RENDER_DPI` | `150` | DPI for page-image rendering |
| `EVALUATOR_MODE` | `mock` | `mock` (offline), `openrouter`, or `anthropic` |
| `OPENROUTER_API_KEY` | _(unset)_ | Required only when `EVALUATOR_MODE=openrouter` |
| `OPENROUTER_MODEL` | `anthropic/claude-3.5-sonnet` | Any OpenRouter model id, e.g. `openai/gpt-4o` |
| `OPENROUTER_API_BASE` | `https://openrouter.ai/api/v1` | Override for a compatible endpoint |
| `ANTHROPIC_API_KEY` | _(unset)_ | Required only when `EVALUATOR_MODE=anthropic` |
| `ANTHROPIC_MODEL` | `claude-sonnet-5` | Any Claude model id, e.g. `claude-haiku-4-5-20251001` |
| `CATALIST_EVAL_MAX_TOKENS` | `1500` | Max output tokens requested from the model |
| `CATALIST_MAX_EVAL_PAGES` | `3` | Max page images sent (visual rubrics only) |
| `CATALIST_IMAGE_MAX_LONG_EDGE` | `1200` | Downscale target (px) before encoding |
| `CATALIST_IMAGE_JPEG_QUALITY` | `80` | JPEG quality for encoded page images |
| `CATALIST_EVAL_TIMEOUT` | `60` | Per-request timeout (seconds) |
| `CATALIST_EVAL_MAX_ATTEMPTS` | `2` | Network attempts on timeout / 5xx |
| `INTAKE_MODE` | `local` | `local` (CSV fixtures) or `google` (Sheets + Drive) |
| `GOOGLE_SHEET_ID` | _(unset)_ | Form-responses spreadsheet id (google mode) |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | _(unset)_ | Path to service-account JSON key (google mode) |
| `CATALIST_CANDIDATE_STORE_PATH` | `backend/data/candidates.json` | JSON candidate store location |
| `CATALIST_JOB_STORE_PATH` | `backend/data/jobs.json` | JSON job store location |
| `CATALIST_DATA_DIR` | `backend/data` | Local working-data directory |
| `EMAIL_MODE` | `mock` | `mock` (writes to outbox) or `resend` (real send) |
| `RESEND_API_KEY` | _(unset)_ | Required only when `EMAIL_MODE=resend` |
| `RESEND_FROM_EMAIL` | _(unset)_ | Verified sender address (resend mode) |
| `ASSIGNMENT_DEADLINE_DAYS` | `5` | Days from send until the assignment deadline |

---

## OpenRouter / going live

Phase 1's default is fully offline (`EVALUATOR_MODE=mock`). To score CVs with a
real vision+text model, use [OpenRouter](https://openrouter.ai) — one
OpenAI-compatible API in front of many models (Claude, GPT-4o, …).

1. **Get a key.** Sign up at <https://openrouter.ai>, add credit, and create a
   key under *Keys*. It looks like `sk-or-v1-...`.
2. **Set the environment** (backend, venv activated):

   ```bash
   export EVALUATOR_MODE=openrouter
   export OPENROUTER_API_KEY=sk-or-v1-...        # your key
   # optional — defaults to anthropic/claude-3.5-sonnet:
   export OPENROUTER_MODEL=openai/gpt-4o
   ```
3. **Run as usual** — the CLI (and any later API wiring) now routes through the
   OpenRouter evaluator with **no code change**:

   ```bash
   python -m app.cli sample_data/sample_cv_text.pdf
   ```

   `evaluated_by` in the output will read `openrouter:<model>` instead of
   `mock`.

**How it fails, on purpose:**
- Missing `OPENROUTER_API_KEY` while in `openrouter` mode → `EvaluatorConfigError`
  (raised on first use, never at import), surfaced by the CLI as a clean
  `error:` line.
- Model returns non-JSON / off-schema output → one automatic corrective retry;
  if it still fails → `EvaluationError`. The real evaluator never silently falls
  back to the mock — that policy decision is left to the caller.
- Transient timeouts / 5xx → up to `CATALIST_EVAL_MAX_ATTEMPTS` network retries
  with short backoff (separate from the JSON retry).

Switching to `openai/gpt-4o` (or any other model) is only the `OPENROUTER_MODEL`
change above.

> **Tests never go live.** The suite stubs the HTTP call with `respx`, so
> `pytest` passes with no key and no network.

---

## Anthropic / going live

To score CVs with Claude via Anthropic's **native** API (instead of OpenRouter):

1. **Get a key** at <https://console.anthropic.com> → *API Keys* (`sk-ant-...`).
2. **Set the environment** (backend, venv activated):

   ```bash
   export EVALUATOR_MODE=anthropic
   export ANTHROPIC_API_KEY=sk-ant-...           # your key (or put it in .env)
   # optional — defaults to claude-sonnet-5:
   export ANTHROPIC_MODEL=claude-sonnet-5
   ```
3. **Run as usual** — the CLI routes through the Anthropic evaluator with **no
   code change**; `evaluated_by` reads `anthropic:<model>`:

   ```bash
   python -m app.cli sample_data/sample_cv_text.pdf
   ```

Same contract as OpenRouter: strict-JSON output, one corrective JSON retry,
network retry-on-timeout/5xx, `EvaluatorConfigError` (missing key, at call time
only) and `EvaluationError` (bad output after retry). The key is read at call
time, so importing/constructing `AnthropicEvaluator` never needs it. Everything
Anthropic-specific (native `image` blocks, SDK call) lives in
`app/evaluation/anthropic_native.py`.

### Conditional vision (`requires_visual_review`)

A `Rubric` carries `requires_visual_review` (default `false`):

- **`false`** — the evaluator sends **text only**. No page images are encoded or
  attached, and the prompt scores content match only. This is the cheaper,
  faster default and the right choice for most roles.
- **`true`** — the evaluator additionally attaches up to `MAX_EVAL_PAGES` page
  images and the prompt scores visual hierarchy / formatting as its own signal.
  Set this for roles where document design matters (e.g. `rubric_design.json`,
  which includes an explicit `visual_hierarchy` criterion).

The behaviour is entirely inside the evaluator — ingestion still just takes a
`Rubric`. `sample_data/rubric.json` is a content-only rubric; `rubric_design.json`
is a visual one.

### Opt-in live smoke test (spends real credits)

There is exactly one live test, **skipped by default**. It evaluates a single
small CV, text-only, on the cheapest model (`claude-haiku-4-5-20251001`) and
asserts a schema-valid `Evaluation`. It requires a real `ANTHROPIC_API_KEY` and
makes one real API call, so run it deliberately:

```bash
RUN_LIVE_SMOKE=1 ANTHROPIC_API_KEY=sk-ant-... pytest -k live_smoke
```

> ⚠️ **Cost warning.** This is the only test that hits the network and it costs
> real Anthropic credits (a few tenths of a cent on Haiku). The normal `pytest`
> run never triggers it — it is gated on `RUN_LIVE_SMOKE`.

> **All other tests never go live.** Both real evaluators are covered fully
> offline by stubbing their httpx traffic with `respx`.

---

## Jobs & ingestion

Everything is scoped to a **job** (its own JD + rubric). Two sample jobs are
declared in `sample_data/jobs_seed.json` — **Backend Engineer** (content-only
rubric) and **Graphic Designer** (visual rubric). Seed them with:

```bash
python -m app.cli seed-jobs          # or: they auto-seed on server start if empty
```

Then ingest per job (defaults: local fixtures + mock, fully offline):

```bash
python -m app.cli ingest backend-engineer
python -m app.cli ingest graphic-designer
```

Each prints the `IngestionSummary` (processed / skipped / failed) and the job's
ranked candidates. Re-running **skips** everything — ingestion dedups by CV file
hash. Over HTTP the same flow is `POST /jobs/{id}/ingest`; then
`GET /jobs/{id}/candidates?tier=&status=` (filter by recommendation tier and/or
status) and `GET /jobs/{id}/summary` (counts by tier + status). `GET /candidates`
still lists everything across jobs.

Dedup is **global** by CV file hash (unchanged from earlier phases), so the
sample fixtures use a distinct CV per candidate. The candidate + job stores are
single JSON files (`backend/data/candidates.json`, `backend/data/jobs.json`) —
deliberate placeholders for the Phase 6 Supabase store.

### Reset candidate data

Phase 5 added `job_id` to `Candidate`. This is pre-production dev data with **no
migration** — old records in `data/candidates.json` predate `job_id`. When this
change lands, reset the candidate store:

```bash
rm -f backend/data/candidates.json
rm -rf backend/data/candidates/          # stale per-candidate artifacts
```

Re-seed jobs and re-ingest per job to repopulate. (Jobs in `data/jobs.json` are
unaffected.)

---

## Google intake / going live

The default `INTAKE_MODE=local` reads a CSV fixture and needs nothing. To ingest
real Google Form responses, switch to `INTAKE_MODE=google`. Candidates apply via
a Google Form with a **file-upload** question for the CV; responses (and the
uploaded Drive files) land in the linked responses Sheet.

1. **Create a Google Cloud project** and enable the **Google Sheets API** and
   **Google Drive API** (APIs & Services → Library).
2. **Create a service account** (IAM & Admin → Service Accounts), then add a
   **JSON key** (Keys → Add key → JSON) and download it. Note the service
   account's email, `...@....iam.gserviceaccount.com`.
3. **Share access with the service account** (it acts as its own identity, not
   you):
   - Open the **form-responses Sheet** → Share → add the service-account email
     as **Viewer**.
   - The CV uploads live in a **Drive folder** owned by the form owner. Share
     that folder (or the files) with the service-account email as **Viewer** so
     it can download them.
4. **Set the environment** (backend, venv activated) and install the Google
   client libraries (they're in `requirements.txt` but only needed for this
   mode):

   ```bash
   pip install google-api-python-client google-auth
   export INTAKE_MODE=google
   export GOOGLE_SHEET_ID=<the spreadsheet id from its URL>
   export GOOGLE_SERVICE_ACCOUNT_FILE=/absolute/path/to/service-account.json
   ```
5. **Run** — the CLI/API pick up the Google source with no code change:

   ```bash
   python -m app.cli ingest <job_id>
   ```

Multi-job note: `GoogleFormsIntakeSource.fetch_new_submissions(job_id=…)` accepts
a `job_id` for interface parity and tags every returned submission with it, but
does not yet map one Google Form/Sheet per job — real per-form configuration is
**forward-looking** (a later concern once a second real form exists). Today all
rows from the single configured sheet are ingested under whichever job you run.

**How it fails, on purpose:** a missing `GOOGLE_SHEET_ID` /
`GOOGLE_SERVICE_ACCOUNT_FILE`, an unreadable key file, or the Google libraries
not being installed raise `IntakeConfigError` — but only when a method actually
runs. Importing the module and constructing `GoogleFormsIntakeSource()` never
require any of them, which is why the test suite covers this source with **no
credentials and the libraries absent**.

The response Sheet's columns are matched by header name (case-insensitive):
name, email, and the CV column (any of *cv / resume / résumé / upload / file*),
whose cell may be a Drive URL (`.../open?id=…` or `.../file/d/…/view`) or a bare
file id.

---

## Assignment email / going live

Shortlisted candidates are emailed a take-home assignment (with
`sample_data/assignment_brief.pdf` attached) via
`POST /candidates/{id}/send-assignment`. The deadline is
`ASSIGNMENT_DEADLINE_DAYS` (default 5) days out.

**Local dev (default, offline).** `EMAIL_MODE=mock` sends nothing — it writes
each message to `data/outbox/<candidate_id>_<timestamp>.json` (recipient,
subject, rendered HTML body, attachment filenames, metadata). Inspect that
folder to see exactly what would have gone out. No key required.

```bash
ls backend/data/outbox/            # one JSON per (re)send
```

**Going live with Resend.** To actually send email, use
[Resend](https://resend.com):

1. **Get a key** at <https://resend.com> → *API Keys* (`re_...`), and verify a
   sending domain / from-address.
2. **Set the environment** (backend, venv activated):

   ```bash
   export EMAIL_MODE=resend
   export RESEND_API_KEY=re_...
   export RESEND_FROM_EMAIL="Catalist Hiring <hire@yourdomain.com>"
   # optional — deadline horizon (days):
   export ASSIGNMENT_DEADLINE_DAYS=5
   ```
3. Send from the dashboard (**Send Assignment** on a shortlisted candidate) or
   via the endpoint — no code change.

Implementation notes: the Resend sender is a plain `httpx` POST (no extra SDK),
reads `RESEND_API_KEY` / `RESEND_FROM_EMAIL` **at call time only** (constructing
it never needs them — missing config raises `EmailConfigError` when `send` runs),
and wraps runtime failures (API rejection, bad recipient, network) into
`EmailSendResult(success=False, error=...)`. The endpoint turns that into a
**502 with the status left unchanged**, so a failed send is always retryable and
never silently advances the candidate. A `force: true` resend is allowed after
`assignment_sent` and increments `assignment_sent_count`.

> **Tests never go live.** `EMAIL_MODE=mock` in tests assert on outbox files; the
> Resend sender is covered with `respx` stubs and a config-error-at-call-time
> check — no key, no network.

### Bulk send

`POST /jobs/{job_id}/send-assignments` sends assignments to many candidates in
one call. **This is what Phase 7's "Send to All Shortlisted" button will call.**

Request body (both fields optional):

```jsonc
{
  "candidate_ids": ["id1", "id2"],  // omit/null -> all of the job's shortlisted
  "force": false                     // resend even if already assignment_sent
}
```

- Omit `candidate_ids` for the common "send to everyone I shortlisted" case.
- Provide `candidate_ids` to target exactly those — each is validated against the
  job; a candidate from a *different* job is flagged `skipped_wrong_job`, not
  processed.
- 404 only if the **job** doesn't exist. Zero eligible candidates (nobody
  shortlisted) is a normal `200` with `requested_count: 0`, not an error.
- Sending is **sequential** (deliberate, for real-provider rate-limit safety).
  One candidate's failure never aborts the batch.

Response (`BulkSendResult`):

```jsonc
{
  "job_id": "backend-engineer",
  "requested_count": 3,
  "sent":    [{ "candidate_id": "…", "success": true,  "status": "sent" }],
  "skipped": [{ "candidate_id": "…", "success": false, "status": "skipped_already_sent", "detail": "…" }],
  "failed":  [{ "candidate_id": "…", "success": false, "status": "failed", "detail": "…" }],
  "sent_count": 1, "skipped_count": 1, "failed_count": 1
}
```

`SendOutcome.status` is one of `sent`, `skipped_not_shortlisted`,
`skipped_already_sent`, `skipped_wrong_job`, `not_found`, `failed`,
`config_error`. Skips and failures carry a human-readable `detail`.

---

## Review dashboard (frontend)

`frontend/` is a Next.js (App Router) + TypeScript + Tailwind app. Phase 7
rebuilt it around the multi-job backend; see
[`frontend/DESIGN_NOTES.md`](frontend/DESIGN_NOTES.md) for the typography/color/
layout rationale (warm-neutral base, dot-based tier chips vs. outline status
pills, slide-over review drawer).

- **`/` Jobs overview** — a card per job with a stacked **tier summary bar** +
  counts and a per-job **Run Ingestion** action.
- **`/jobs/[id]` Pipeline** — collapsible JD + summary; **tabs** Shortlist /
  Borderline / Reject / All. Every row shows **both** the AI tier chip and the
  human decision status (distinct visual languages). The **Shortlist tab** is the
  send workspace (AI-shortlist **∪** anyone you've shortlisted) with multi-select
  + **Send to Selected** → `POST /jobs/{id}/send-assignments`, and a visible
  **sent / skipped / failed** result summary. Rows open a **slide-over** detail.
- **Candidate detail** (slide-over, or full-page `/candidates/[id]`) — CV page
  images, per-criterion evidence-backed scores, overall score + AI
  recommendation, the re-decidable **Shortlist / Reject** gate, and a **secondary**
  single Send/Resend assignment for one-off cases.

It talks to the backend via `NEXT_PUBLIC_API_BASE_URL` (default
`http://localhost:8000`).

### Run backend + frontend together (local, fully offline)

Two terminals from the repo root.

**1. Backend** (mock evaluator + local fixtures — no keys needed):

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload        # http://localhost:8000
```

**2. Frontend:**

```bash
cd frontend
npm install
npm run dev                          # http://localhost:3000
```

Then, in the browser at <http://localhost:3000>: the **Jobs overview** lists the
seeded jobs (they auto-seed on server start). Click **Run ingestion** on a job to
pull + score its applicants, **Open pipeline**, review candidates across the
tier tabs, open a row for detail, **Shortlist/Reject** with a note, then
multi-select in the Shortlist tab and **Send to Selected** to dispatch
assignments — the sent/skipped/failed summary shows inline.

If the backend runs elsewhere, point the frontend at it:

```bash
NEXT_PUBLIC_API_BASE_URL=http://my-backend:8000 npm run dev
```

Production build check (no type errors): `npm run build`.
