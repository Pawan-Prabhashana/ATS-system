# Catalist frontend — design notes (Phase 8 rebuild + redesign)

> The `frontend-design` skill isn't installed on this machine, so this applies its
> method directly: pin the brief, name a token system, choose typefaces with real
> roles, commit to a layout + one signature element, and self-critique against the
> generic defaults before building.

## The brief (pinned)

An **internal ATS triage cockpit** for a small recruiting team at a media company.
One operator, moving fast: reviewing AI-scored candidates and configuring a handful
of open roles. **Each screen has one job.** Density, speed-to-scan, and trust beat
marketing gloss — but *internal ≠ ugly*.

## What we are NOT shipping — the three AI defaults

1. **Warm cream/stone bg + serif display + terracotta/clay accent** — **this is the
   current UI.** We move to a *cool* slate workspace; no serif; no clay.
2. **Near-black canvas + one acid-green/vermilion accent** — we are a *light*,
   multi-hue instrument; the accent is a considered blue, never neon-on-black.
3. **Broadsheet hairline-rule newspaper columns** — we use panelled, tabular
   density, not thin editorial rules and column measures.

## Direction: "control surface"

A calm, **cool** workspace that reads like an instrument, not a document. A fixed
left rail (workspace navigation) beside a dense main surface. Numbers everywhere are
monospaced so scores line up like a readout.

## Core palette — 6 named tokens (cool, deliberate)

| token | hex | role |
| --- | --- | --- |
| `--bg` | `#EEF2F6` | cool paper (blue-gray — **not** warm cream) |
| `--surface` | `#FFFFFF` | panels / cards |
| `--ink` | `#141B2B` | blue-black text (not pure or warm black) |
| `--muted` | `#64748B` | secondary text / meta |
| `--line` | `#DCE3EC` | hairlines / borders |
| `--accent` | `#2E56E6` | **signal blue** — interactive + active, used sparingly |

A cohesive dark variant is defined on the same tokens; we ship light-first for
daytime desk use.

## The signature — the two-axis signal ("the verdict track")

The AI **recommendation** (tier) and the human **decision** (status) are *different
axes* and must never collapse into one indicator. We encode that **structurally**,
two reinforcing ways at once:

1. **Different colour families.** The eye separates them pre-attentively.
   - **AI tier** — a signal set: shortlist `#1C8B5A` (green) · borderline `#C0872B`
     (gold) · reject `#CE4257` (rose).
   - **Human decision** — a cool action set: undecided = *hollow* · shortlisted
     `#2E56E6` (accent blue) · rejected `#3A4557` (graphite) · assignment sent
     `#6D4AE0` (violet).
2. **The verdict track** — a small two-node motif per candidate: **node 1** (filled,
   AI-tier colour) → short connector → **node 2** (human decision). Undecided is a
   *hollow dashed ring* ("awaiting you"); decided fills with a glyph. It reads
   left-to-right as **"machine suggested → you decided."** An override (AI *reject* →
   you *shortlist*) shows as **rose → blue** — instantly legible as a deliberate
   disagreement. The motif recurs in rows, the detail header, and summaries; it is
   the thing the tool is remembered by.

## Typography — 3 faces, 3 roles

- **Display** (headings, job titles): **Space Grotesk** — geometric, faintly
  technical; an instrument voice, not an editorial serif.
- **Body / UI** (labels, prose, controls): **Inter** — neutral workhorse for dense
  interfaces.
- **Numeric** (scores, weights, counts, ids): **JetBrains Mono** — tabular figures;
  scores read as a readout and align down columns.

All three via `next/font` (Google). Distinct roles = not a single-font default.

## Layout concept

- **Fixed left rail** — workspace nav (Jobs · New job; within a job: Pipeline ·
  Settings). A cockpit pattern that differentiates structurally from the current
  top-nav centered pages and matches "operator tool." Collapses to a top bar under
  ~768px.
- **Main surface** — panelled cards + a dense candidate table. The pipeline keeps its
  tab + slide-over bones (reskinned), per the brief.

## Self-critique vs the brief

- First instinct kept tiers in **teal/ochre/clay** (the current look) — **changed** to
  green/gold/rose, and moved the human decision to a **separate blue/graphite/violet
  family** so the two axes separate by *hue*, not just by badge shape.
- First instinct reused a **top-nav centered** layout (current) — **changed** to a
  fixed left rail so it reads as a tool, not a document.
- Considered a single combined **"tier+status" chip** — **rejected**: it collapses the
  two axes (violates the brief). The verdict track keeps them structurally separate.
- Space Grotesk + Inter is a known SaaS pairing; **kept** because it is deliberate and
  clearly off all three named defaults, with JetBrains Mono giving the numeric readout
  its own voice.

## Quality floor (not announced in the UI)

Responsive to mobile; a visible keyboard focus ring; `prefers-reduced-motion` honored
(slide-over / track transitions gated); copy in sentence case, naming things by what
the operator controls; empty and error states give direction in the tool's voice.

## Phase 12 — polish + branding (elevate, don't replace)

The control-surface system is unchanged; Phase 12 adds depth and hierarchy on top.

- **Elevation tokens** (`globals.css`): `--shadow-sm/md/lg` (soft, cool-tinted; they
  deepen in dark mode, where raised surfaces also lighten). Applied through the
  shared `Card` (base `shadow-sm`, optional `elevated` hover-lift) and `Button`
  (primary carries a shadow), so depth propagates app-wide from two components.
- **Logo**: `public/Catalist-logo.jpeg` — a dark rounded tile. Always contained in
  a `rounded` box with a `ring-1 ring-line-2` so the JPEG (no transparency) never
  shows a hard box on light/dark surfaces. Used in the rail brand, `/login`, and
  the favicon.
- **Jobs landing**: an overview strip of aggregate `StatTile`s (open roles,
  candidates, shortlisted, assignments sent) fills the former empty top; job cards
  became mini-dashboards (tier bar + per-tier count tiles, connection status with
  an icon, hover lift, primary "Open pipeline" vs secondary ingest/settings). A
  3-column grid (`xl`) uses the wide space; empty states are designed moments.
- **Login** (`/login`): full-bleed, ambient accent glow (no motion), branded card.
- Reduced-motion is honored globally (the existing media query zeroes transitions),
  so every hover-lift / micro-transition degrades to instant.
