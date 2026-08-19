import type { CandidateStatus, Recommendation } from "@/lib/api";

// AI recommendation (tier) — the "signal" colour family.
export const TIER_META: Record<
  Recommendation,
  { label: string; color: string; tint: string }
> = {
  shortlist: { label: "Shortlist", color: "var(--tier-shortlist)", tint: "var(--tier-shortlist-tint)" },
  borderline: { label: "Borderline", color: "var(--tier-borderline)", tint: "var(--tier-borderline-tint)" },
  reject: { label: "Reject", color: "var(--tier-reject)", tint: "var(--tier-reject-tint)" },
};
export const TIER_ORDER: Recommendation[] = ["shortlist", "borderline", "reject"];

// Human decision (status) — a distinct cool "action" family.
type DecisionKind = "undecided" | "positive" | "negative" | "sent";
export const DECISION_META: Record<
  CandidateStatus,
  { label: string; kind: DecisionKind; color: string }
> = {
  parsed: { label: "Awaiting review", kind: "undecided", color: "var(--faint)" },
  scored: { label: "Awaiting review", kind: "undecided", color: "var(--faint)" },
  shortlisted: { label: "Shortlisted", kind: "positive", color: "var(--dec-shortlisted)" },
  rejected: { label: "Rejected", kind: "negative", color: "var(--dec-rejected)" },
  assignment_sent: { label: "Assignment sent", kind: "sent", color: "var(--dec-sent)" },
  submitted: { label: "Submitted", kind: "sent", color: "var(--dec-sent)" },
};

// A tiny white glyph inside a decided node — shape reinforces hue, so the
// signal survives colourblindness and small sizes.
function Glyph({ kind, px }: { kind: DecisionKind; px: number }) {
  const s = {
    fill: "none",
    stroke: "#fff",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  return (
    <svg viewBox="0 0 16 16" width={px} height={px} aria-hidden>
      {kind === "positive" && <path d="M4 8.4l2.6 2.6L12 5.4" {...s} />}
      {kind === "negative" && <path d="M5 5l6 6M11 5l-6 6" {...s} />}
      {kind === "sent" && <path d="M4 8h7M8 4.5L11.5 8 8 11.5" {...s} />}
    </svg>
  );
}

/**
 * The signature. Two nodes — AI tier (left) → your decision (right) — reading
 * "machine suggested → you decided." Undecided is a hollow dashed ring
 * ("awaiting you"); an override shows as a tier/decision colour mismatch.
 */
export function VerdictTrack({
  tier,
  status,
  size = "sm",
}: {
  tier: Recommendation | null;
  status: CandidateStatus;
  size?: "sm" | "md";
}) {
  const dec = DECISION_META[status];
  const n1 = size === "md" ? 14 : 11;
  const n2 = size === "md" ? 16 : 13;
  const glyph = size === "md" ? 11 : 9;
  const line = size === "md" ? 14 : 11;
  const label = `AI ${tier ? TIER_META[tier].label.toLowerCase() : "unscored"}; your decision: ${dec.label.toLowerCase()}`;

  return (
    <span
      className="inline-flex items-center"
      role="img"
      aria-label={label}
      title={label}
    >
      {/* node 1 — AI tier */}
      {tier ? (
        <span
          style={{ width: n1, height: n1, background: TIER_META[tier].color }}
          className="inline-block rounded-full"
        />
      ) : (
        <span
          style={{ width: n1, height: n1, borderColor: "var(--faint)" }}
          className="inline-block rounded-full border-[1.5px]"
        />
      )}
      {/* connector */}
      <span style={{ width: line, height: 1.5, background: "var(--line-2)" }} className="inline-block" />
      {/* node 2 — your decision */}
      {dec.kind === "undecided" ? (
        <span
          style={{ width: n2, height: n2, borderColor: "var(--faint)" }}
          className="inline-grid place-items-center rounded-full border-[1.5px] border-dashed"
        />
      ) : (
        <span
          style={{ width: n2, height: n2, background: dec.color }}
          className="inline-grid place-items-center rounded-full"
        >
          <Glyph kind={dec.kind} px={glyph} />
        </span>
      )}
    </span>
  );
}

/** Compact tier label (dot + text) for headers/filters. */
export function TierChip({ tier, size = "sm" }: { tier: Recommendation; size?: "sm" | "md" }) {
  const m = TIER_META[tier];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-medium ${
        size === "md" ? "px-2.5 py-1 text-[13px]" : "px-2 py-0.5 text-xs"
      }`}
      style={{ background: m.tint, color: m.color }}
    >
      <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: m.color }} />
      {m.label}
    </span>
  );
}

/** Human decision label (glyph + text), the cool family. */
export function DecisionChip({ status }: { status: CandidateStatus }) {
  const m = DECISION_META[status];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium"
      style={{
        color: m.kind === "undecided" ? "var(--muted)" : m.color,
        borderColor:
          m.kind === "undecided"
            ? "var(--line-2)"
            : `color-mix(in srgb, ${m.color} 40%, transparent)`,
        background:
          m.kind === "undecided"
            ? "transparent"
            : `color-mix(in srgb, ${m.color} 9%, transparent)`,
      }}
    >
      {m.kind !== "undecided" && (
        <span
          className="inline-grid h-3.5 w-3.5 place-items-center rounded-full"
          style={{ background: m.color }}
        >
          <Glyph kind={m.kind} px={9} />
        </span>
      )}
      {m.label}
    </span>
  );
}

/** Slim stacked tier bar for summaries. */
export function TierBar({
  counts,
  total,
}: {
  counts: Record<Recommendation, number>;
  total: number;
}) {
  const denom = total || 1;
  return (
    <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
      {TIER_ORDER.map((t) => {
        const pct = (counts[t] / denom) * 100;
        if (pct <= 0) return null;
        return (
          <div
            key={t}
            style={{ width: `${pct}%`, background: TIER_META[t].color }}
            title={`${TIER_META[t].label}: ${counts[t]}`}
          />
        );
      })}
    </div>
  );
}
