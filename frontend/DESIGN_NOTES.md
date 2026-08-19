# Catalist frontend — design notes (Phase 7)

## On the design skill

Phase 7 asked me to read `/mnt/skills/public/frontend-design/SKILL.md` first. **That
file does not exist on this machine** (only unrelated `dotenv` skill files are
present, and it isn't in the loadable skill set). Rather than fabricate having
read it, I applied a deliberate, self-consistent design system and documented
every decision here so the reasoning is auditable. If the skill becomes
available, this doc is the place to reconcile against it.

## Goals

Internal review tool for a small team. Optimize for **speed-to-scan** and
**unambiguous signals**, not decoration — but avoid the "unstyled Tailwind admin"
look the previous UI had.

## Typography

- **Geist Sans** for UI, **Geist Mono** for all numerics and IDs (scores,
  counts, candidate ids). Numbers use `tabular-nums` so decimals align in lists
  — a CV pipeline is a data instrument, and mono numerics read as "measured."
- Tight tracking on headings (`tracking-tight`); a crisp, editorial feel.
- Section headers are **quiet uppercase micro-labels** (11px, `0.08em` tracking,
  muted) instead of loud bold — hierarchy through restraint, not weight.

## Color

- **Warm-neutral "stone" base** (`--bg #faf9f7`, `--ink #1c1917`) rather than the
  cold blue-gray that reads as "default admin." Cards are white on the warm
  ground with hairline borders.
- **Primary actions are near-black ink**, not a saturated brand blue — timeless,
  high-contrast, and it lets the tier colors be the only saturated thing on
  screen. Links use one restrained blue.

### Tier palette (the deliberate anti-"alert box" choice)

Tiers are **not** red/amber/green fills. Each tier is a small **saturated dot +
colored text on a very light tint chip**:

| Tier | Hue | Why |
| --- | --- | --- |
| Shortlist | deep **teal** | positive, but calmer/more considered than a "success green" |
| Borderline | **ochre**/amber | caution without the traffic-light yellow |
| Reject | muted **clay-rose** | clearly negative, but not a fire-engine error red |

The dot carries the color; the chip background stays a near-neutral tint. This
reads instantly at a glance without shouting, and the same three hues drive the
**stacked `TierBar`** on job cards / the pipeline summary for at-a-glance triage.

### AI tier vs. human decision — kept visually distinct

A hard requirement: the AI recommendation and the human decision must never
collapse into one indicator. They use **different visual languages**:

- **AI tier** → filled **dot-chip** (dot + label on tint).
- **Human status** → **outlined pill** (border, mostly no fill), with a leading
  dot only for the "action taken" states (`assignment_sent` / `submitted`, in
  indigo). "Undecided" is a quiet muted outline.

So a candidate the AI rejected but a human shortlisted shows a **clay "Reject"
dot-chip next to a teal "Shortlisted" outline pill** — unmistakably two signals.

## Layout & interaction

- **Jobs overview**: cards, each with the stacked tier bar + counts and a per-job
  "Run ingestion" (fixes the previously-dead button).
- **Pipeline**: refined table (generous row rhythm, avatar initials, hover), a
  right-anchored summary card, and **segmented underline tabs** (dot + count) —
  not default browser tabs.
- **Detail is a right-side slide-over drawer**, not a full-page nav. For triaging
  many candidates, staying in the tab context is faster; the drawer animates in
  with a subtle backdrop. A full-page `/candidates/[id]` route reuses the same
  panel for deep links.
- 8px spacing rhythm; `max-w-7xl`; `focus-visible` ring for keyboard a11y; thin
  scrollbars in scroll regions; minimal, purposeful motion only.
- **Dark mode** is token-based (surfaces/text adapt; tier hues brightened).

## States (designed, not afterthoughts)

- Job with no candidates → prompt + inline "Run ingestion".
- Empty tier tab → clear "No candidates in this tier," never a blank screen.
- Ingestion / bulk send → button spinners; bulk send disables double-submit.
- **Bulk result panel** distinguishes **failed** (clay, "needs attention," with
  per-candidate reasons) from **skipped** (muted, "expected: not shortlisted /
  already sent / wrong job") — they mean different things.

## One product decision worth flagging

The spec says tabs are "backed by the `tier` query param," but the walkthrough
requires that overriding an **AI-reject** candidate to **human-shortlist** makes
it appear **in the Shortlist tab** (the send workspace). Those are in tension —
strict AI-tier filtering would keep that candidate in the Reject tab only.

**Resolution:** the Shortlist tab is a **union** — AI-tier `shortlist` **plus**
anyone with human status `shortlisted` (from any tier). The other tabs
(Borderline / Reject / All) are pure tier views. Every row shows both badges, so
an override reads as "Reject (AI) · Shortlisted (you)". The pipeline fetches the
job's candidates once and derives the tabs client-side so counts and contents
stay consistent (identical to what the server's `tier`/`status` filters return).
