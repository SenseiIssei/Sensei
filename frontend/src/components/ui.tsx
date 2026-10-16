import type { ButtonHTMLAttributes, ReactNode } from "react";
import clsx from "clsx";

/**
 * The handful of primitives every screen is built from.
 *
 * Proportions follow dpm.lol and Odysync: 32px controls with a 6px radius,
 * 12px-radius cards on a hairline border, 11px uppercase labels, tabular
 * numbers. Colour comes only from the theme tokens in index.css, so nothing
 * here knows whether it is light or dark.
 */

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-accent-fg hover:bg-accent-hover",
  secondary: "border border-line-strong bg-surface text-fg hover:bg-raised",
  ghost: "text-muted hover:bg-hover hover:text-fg",
  danger: "border border-danger/25 bg-danger/10 text-danger hover:bg-danger/15",
};

export function Button({
  variant = "secondary",
  size = "md",
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return (
    <button
      className={clsx(
        "inline-flex shrink-0 items-center justify-center gap-2 rounded-sm font-semibold",
        "transition-colors duration-150 ease-calm",
        "disabled:pointer-events-none disabled:opacity-50",
        size === "sm" ? "h-7 px-2.5 text-xs" : "h-8 px-3 text-[13px]",
        VARIANTS[variant],
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

export function IconButton({
  label,
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      aria-label={label}
      title={label}
      className={clsx(
        "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-sm text-muted",
        "transition-colors duration-150 ease-calm hover:bg-hover hover:text-fg",
        "disabled:pointer-events-none disabled:opacity-50",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

export function Card({
  title,
  description,
  actions,
  padded = true,
  className,
  children,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  padded?: boolean;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <section
      className={clsx(
        "animate-fade-in min-w-0 rounded-lg border border-line bg-surface shadow-sm dark:shadow-none",
        padded && "p-5",
        className,
      )}
    >
      {(title || actions) && (
        <header
          className={clsx("flex items-start justify-between gap-3", !padded && "px-5 pt-5", "mb-4")}
        >
          <div className="min-w-0">
            {title && <h2 className="text-[15px] font-semibold leading-[22px] text-fg">{title}</h2>}
            {description && <p className="mt-0.5 text-xs text-muted">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function StatTile({
  label,
  value,
  sub,
  icon,
  highlight = false,
}: {
  label: string;
  value: string;
  sub?: ReactNode;
  icon?: ReactNode;
  /** The one number the page is about. Gold, at most once per view. */
  highlight?: boolean;
}) {
  return (
    <div className="animate-fade-in rounded-lg border border-line bg-surface p-4 shadow-sm dark:shadow-none">
      <p className="eyebrow flex items-center gap-1.5 text-muted">
        {icon}
        {label}
      </p>
      <p
        className={clsx(
          "num mt-2 text-[28px] font-bold leading-9 tracking-[-0.02em]",
          highlight ? "text-gold-text" : "text-fg",
        )}
      >
        {value}
      </p>
      {sub && <p className="mt-1 text-xs text-muted">{sub}</p>}
    </div>
  );
}

type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "info";

const TONES: Record<Tone, string> = {
  neutral: "border-line-strong bg-raised text-muted",
  accent: "border-accent/25 bg-accent/12 text-accent",
  success: "border-success/25 bg-success/12 text-success",
  warning: "border-warning/25 bg-warning/12 text-warning",
  danger: "border-danger/25 bg-danger/12 text-danger",
  info: "border-info/25 bg-info/12 text-info",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-xs border px-1.5 py-0.5 text-[11px] font-semibold leading-4",
        TONES[tone],
      )}
    >
      {children}
    </span>
  );
}

export function Notice({
  tone = "info",
  icon,
  children,
  action,
}: {
  tone?: Tone;
  icon?: ReactNode;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div
      className={clsx(
        "flex flex-wrap items-start gap-3 rounded-md border px-4 py-3 text-[13px] leading-5",
        tone === "neutral" ? "border-line bg-surface text-fg-secondary" : TONES[tone],
      )}
    >
      {icon && <span className="mt-0.5 shrink-0">{icon}</span>}
      <div className="min-w-0 flex-1 text-fg-secondary">{children}</div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="flex items-center gap-3 text-2xl font-semibold leading-8 tracking-[-0.01em] text-fg">
          {title}
        </h1>
        {description && <p className="mt-1 text-[13px] text-muted">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded-xs border border-line bg-raised px-1.5 py-px font-mono text-[11px] text-faint">
      {children}
    </kbd>
  );
}

/** A copyable one-liner, for commands and URLs the user will paste elsewhere. */
export function CodeLine({ children }: { children: string }) {
  return (
    <div className="group flex items-center gap-2 rounded-md border border-line bg-code-bg px-3 py-2">
      <code className="min-w-0 flex-1 overflow-x-auto whitespace-pre font-mono text-[13px] text-fg scrollbar-thin">
        {children}
      </code>
      <button
        onClick={() => void navigator.clipboard?.writeText(children)}
        className="shrink-0 rounded-xs px-1.5 py-0.5 text-[11px] font-semibold text-faint transition-colors hover:bg-hover hover:text-fg"
      >
        Copy
      </button>
    </div>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string; icon?: ReactNode }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex rounded-sm border border-line bg-canvas p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          role="radio"
          aria-checked={value === option.value}
          title={option.label}
          onClick={() => onChange(option.value)}
          className={clsx(
            "flex h-7 flex-1 items-center justify-center gap-1.5 rounded-xs px-2 text-xs font-medium",
            "transition-colors duration-150 ease-calm",
            value === option.value ? "bg-raised text-fg shadow-sm" : "text-muted hover:text-fg",
          )}
        >
          {option.icon}
          <span className={option.icon ? "sr-only" : undefined}>{option.label}</span>
        </button>
      ))}
    </div>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 100 100" className={className} aria-hidden="true">
      <rect width="100" height="100" rx="22" fill="var(--canvas)" stroke="var(--line-strong)" strokeWidth="3" />
      <path
        d="M24 34h52M32 51h36M40 68h20"
        stroke="var(--accent)"
        strokeWidth="8.5"
        strokeLinecap="round"
      />
      <circle cx="72" cy="68" r="5.5" fill="var(--gold)" />
    </svg>
  );
}
