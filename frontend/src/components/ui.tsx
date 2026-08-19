import type { ButtonHTMLAttributes, ReactNode } from "react";

// -- Button -----------------------------------------------------------------
type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const VARIANT: Record<Variant, string> = {
  primary:
    "bg-ink text-[var(--bg)] hover:opacity-90 disabled:opacity-40",
  secondary:
    "bg-surface text-ink border border-line-2 hover:bg-surface-2 disabled:opacity-40",
  ghost:
    "bg-transparent text-ink-2 hover:bg-surface-2 hover:text-ink disabled:opacity-40",
  danger:
    "bg-transparent text-[var(--tier-reject)] border border-[var(--tier-reject)]/40 hover:bg-[var(--tier-reject-tint)] disabled:opacity-40",
};

const SIZE: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px] gap-1.5 rounded-md",
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
      className={`inline-flex items-center justify-center font-medium tracking-tight transition-[opacity,background-color,color] disabled:cursor-not-allowed ${VARIANT[variant]} ${SIZE[size]} ${className}`}
      {...rest}
    >
      {loading && <Spinner className="-ml-0.5" />}
      {children}
    </button>
  );
}

// -- Spinner ----------------------------------------------------------------
export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      className={`inline-block h-3.5 w-3.5 animate-spin rounded-full border-[1.5px] border-current border-t-transparent ${className}`}
      aria-hidden
    />
  );
}

// -- Card -------------------------------------------------------------------
export function Card({
  className = "",
  children,
  ...rest
}: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`rounded-xl border border-line bg-surface ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}

// -- Checkbox ---------------------------------------------------------------
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
      role="checkbox"
      aria-checked={indeterminate ? "mixed" : checked}
      aria-label={ariaLabel}
      onClick={(e) => {
        e.stopPropagation();
        onChange(!checked);
      }}
      className={`grid h-[18px] w-[18px] place-items-center rounded-[5px] border transition-colors ${
        checked || indeterminate
          ? "border-ink bg-ink text-[var(--bg)]"
          : "border-line-2 bg-surface hover:border-ink-2"
      }`}
    >
      {indeterminate ? (
        <span className="h-[2px] w-2.5 rounded bg-current" />
      ) : checked ? (
        <svg viewBox="0 0 12 12" className="h-3 w-3" fill="none">
          <path
            d="M2.5 6.2l2.2 2.2 4.8-4.8"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      ) : null}
    </button>
  );
}

// -- Section label ----------------------------------------------------------
export function Label({ children }: { children: ReactNode }) {
  return (
    <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted">
      {children}
    </div>
  );
}
