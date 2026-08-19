import type { CandidateStatus, Recommendation } from "@/lib/api";

// AI tier metadata. Color is carried by a small dot + text — never a loud fill.
export const TIER_META: Record<
  Recommendation,
  { label: string; text: string; dot: string; tint: string; order: number }
> = {
  shortlist: {
    label: "Shortlist",
    text: "var(--tier-shortlist)",
    dot: "var(--tier-shortlist-dot)",
    tint: "var(--tier-shortlist-tint)",
    order: 0,
  },
  borderline: {
    label: "Borderline",
    text: "var(--tier-borderline)",
    dot: "var(--tier-borderline-dot)",
    tint: "var(--tier-borderline-tint)",
    order: 1,
  },
  reject: {
    label: "Reject",
    text: "var(--tier-reject)",
    dot: "var(--tier-reject-dot)",
    tint: "var(--tier-reject-tint)",
    order: 2,
  },
};

export const TIER_ORDER: Recommendation[] = ["shortlist", "borderline", "reject"];

/** AI recommendation, shown as a dot + label chip. */
export function TierChip({
  tier,
  size = "sm",
}: {
  tier: Recommendation;
  size?: "sm" | "md";
}) {
  const m = TIER_META[tier];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-medium ${
        size === "md" ? "px-2.5 py-1 text-[13px]" : "px-2 py-0.5 text-xs"
      }`}
      style={{ background: m.tint, color: m.text }}
    >
      <span
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ background: m.dot }}
      />
      {m.label}
    </span>
  );
}

/** Slim horizontal stacked bar of tier proportions, for at-a-glance triage. */
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
            style={{ width: `${pct}%`, background: TIER_META[t].dot }}
            title={`${TIER_META[t].label}: ${counts[t]}`}
          />
        );
      })}
    </div>
  );
}

// -- Human decision status --------------------------------------------------
// Deliberately a different visual language from TierChip: an outlined pill, so
// the AI recommendation and the human decision never read as one signal.
const STATUS_META: Record<
  CandidateStatus,
  { label: string; color: string; strong?: boolean }
> = {
  parsed: { label: "Undecided", color: "var(--muted)" },
  scored: { label: "Undecided", color: "var(--muted)" },
  shortlisted: { label: "Shortlisted", color: "var(--tier-shortlist)" },
  rejected: { label: "Rejected", color: "var(--tier-reject)" },
  assignment_sent: { label: "Assignment sent", color: "var(--status-sent)", strong: true },
  submitted: { label: "Submitted", color: "var(--status-sent)", strong: true },
};

export function StatusBadge({ status }: { status: CandidateStatus }) {
  const m = STATUS_META[status];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium"
      style={{
        color: m.color,
        borderColor: "color-mix(in srgb, " + m.color + " 35%, transparent)",
        background: m.strong
          ? "color-mix(in srgb, " + m.color + " 8%, transparent)"
          : "transparent",
      }}
    >
      {m.strong && (
        <span
          className="inline-block h-1.5 w-1.5 rounded-full"
          style={{ background: m.color }}
        />
      )}
      {m.label}
    </span>
  );
}
