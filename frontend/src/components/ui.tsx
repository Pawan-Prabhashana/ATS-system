import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const VARIANT: Record<Variant, string> = {
  primary:
    "bg-accent text-white shadow-[var(--shadow-sm)] hover:brightness-95 hover:shadow-[var(--shadow-md)] disabled:opacity-40 disabled:shadow-none",
  secondary: "bg-surface text-ink border border-line-2 hover:bg-surface-2 disabled:opacity-40",
  ghost: "bg-transparent text-muted hover:bg-surface-2 hover:text-ink disabled:opacity-40",
  danger:
    "bg-transparent text-[var(--tier-reject)] border border-[color-mix(in_srgb,var(--tier-reject)_40%,transparent)] hover:bg-[var(--tier-reject-tint)] disabled:opacity-40",
};
const SIZE: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px] gap-1.5 rounded-lg",
  md: "h-9 px-4 text-sm gap-2 rounded-lg",
};

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  className = "",
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}) {
  return (
    <button
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center font-medium tracking-tight transition duration-150 ease-out active:translate-y-px disabled:cursor-not-allowed disabled:active:translate-y-0 ${VARIANT[variant]} ${SIZE[size]} ${className}`}
      {...rest}
    >
      {loading && <Spinner className="-ml-0.5" />}
      {children}
    </button>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      className={`inline-block h-3.5 w-3.5 animate-spin rounded-full border-[1.5px] border-current border-t-transparent ${className}`}
      aria-hidden
    />
  );
}

export function Card({
  className = "",
  elevated = false,
  children,
  ...rest
}: {
  className?: string;
  /** Add a hover lift + deeper shadow (for clickable cards). */
  elevated?: boolean;
  children: ReactNode;
} & React.HTMLAttributes<HTMLDivElement>) {
  const lift = elevated
    ? "transition-[box-shadow,transform,border-color] duration-200 ease-out hover:-translate-y-0.5 hover:border-line-2 hover:shadow-[var(--shadow-md)]"
    : "";
  return (
    <div
      className={`rounded-xl border border-line bg-surface shadow-[var(--shadow-sm)] ${lift} ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}

/** A compact readout tile: big monospaced value over a small uppercase label,
 *  with an optional leading icon and accent color. Used in overview strips and
 *  the pipeline summary. */
export function StatTile({
  label,
  value,
  icon,
  tone,
  className = "",
}: {
  label: string;
  value: ReactNode;
  icon?: ReactNode;
  tone?: string; // a CSS color for the value + icon (defaults to ink)
  className?: string;
}) {
  return (
    <div className={`rounded-xl border border-line bg-surface p-3.5 shadow-[var(--shadow-sm)] ${className}`}>
      <div className="flex items-center gap-1.5 text-faint">
        {icon && (
          <span className="grid h-3.5 w-3.5 place-items-center" style={tone ? { color: tone } : undefined}>
            {icon}
          </span>
        )}
        <span className="truncate text-[10px] font-medium uppercase tracking-[0.06em]">{label}</span>
      </div>
      <div
        className="mt-1 font-mono text-[22px] font-semibold leading-none tabular-nums"
        style={tone ? { color: tone } : undefined}
      >
        {value}
      </div>
    </div>
  );
}

export function Label({ children }: { children: ReactNode }) {
  return (
    <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-faint">
      {children}
    </div>
  );
}

export function Checkbox({
  checked,
  onChange,
  "aria-label": ariaLabel,
  indeterminate = false,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  "aria-label"?: string;
  indeterminate?: boolean;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={indeterminate ? "mixed" : checked}
      aria-label={ariaLabel}
      onClick={(e) => {
        e.stopPropagation();
        onChange(!checked);
      }}
      className={`grid h-[18px] w-[18px] shrink-0 place-items-center rounded-[5px] border transition-colors ${
        checked || indeterminate
          ? "border-accent bg-accent text-white"
          : "border-line-2 bg-surface hover:border-muted"
      }`}
    >
      {indeterminate ? (
        <span className="h-[2px] w-2.5 rounded bg-current" />
      ) : checked ? (
        <svg viewBox="0 0 12 12" className="h-3 w-3" fill="none">
          <path
            d="M2.5 6.2l2.2 2.2 4.8-4.8"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      ) : null}
    </button>
  );
}

// -- form controls ----------------------------------------------------------
const CONTROL =
  "w-full rounded-lg border border-line-2 bg-surface px-3 py-2 text-sm text-ink placeholder:text-faint focus:border-accent focus:outline-none focus:ring-2 focus:ring-[var(--accent-tint)]";

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${CONTROL} ${props.className ?? ""}`} />;
}

export function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`${CONTROL} resize-y ${props.className ?? ""}`} />;
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-ink">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}
