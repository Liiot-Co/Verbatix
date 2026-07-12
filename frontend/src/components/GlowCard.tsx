import type { ReactNode, MouseEventHandler } from "react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/cn";

/** Soft corner-glow presets (lavender, peach, dual). */
export type GlowCardVariant = 1 | 2 | 3;

const GLOW_CLASS: Record<GlowCardVariant, string> = {
  1: "glow-card-1",
  2: "glow-card-2",
  3: "glow-card-3",
};

/** Pick a glow variant by index (cycles 1 → 2 → 3). */
export function glowVariantForIndex(index: number): GlowCardVariant {
  return ((index % 3) + 1) as GlowCardVariant;
}

export interface GlowCardProps {
  /** Small uppercase-style label at the top (e.g. code, metric name). */
  label?: ReactNode;
  /** Primary text — bold title or main value. */
  title?: ReactNode;
  /** Secondary line under the title. */
  footer?: ReactNode;
  /** Free-form body; used instead of (or in addition to) label/title/footer. */
  children?: ReactNode;
  /** Corner glow style. Defaults to lavender. */
  variant?: GlowCardVariant;
  /** If set, renders as a React Router `Link`. */
  to?: string;
  /** If set (and no `to`), renders as an anchor. */
  href?: string;
  onClick?: MouseEventHandler<HTMLElement>;
  className?: string;
  contentClassName?: string;
  /** Accessible name when the visible text isn’t enough. */
  "aria-label"?: string;
}

/**
 * Compact white card with a soft clipped corner glow.
 * Use for recent items, stats, or any short summary tile.
 */
export default function GlowCard({
  label,
  title,
  footer,
  children,
  variant = 1,
  to,
  href,
  onClick,
  className,
  contentClassName,
  "aria-label": ariaLabel,
}: GlowCardProps) {
  const classes = cn(
    "glow-card",
    GLOW_CLASS[variant],
    "px-3.5 py-3 text-left space-y-1 group block",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-p-accent/40",
    "hover:-translate-y-0.5 hover:shadow-card-hover active:scale-[0.98] transition-all duration-200",
    (to || href || onClick) && "cursor-pointer",
    className
  );

  const body = (
    <div className={cn("relative space-y-1", contentClassName)}>
      {label != null && (
        <div className="text-[10px] font-semibold tracking-[0.06em] uppercase text-p-text-faint truncate">
          {label}
        </div>
      )}
      {title != null && (
        <div className="text-sm font-bold text-p-text leading-snug truncate">
          {title}
        </div>
      )}
      {footer != null && (
        <div className="text-[11px] font-subtitle text-p-text-muted">
          {footer}
        </div>
      )}
      {children}
    </div>
  );

  if (to) {
    return (
      <Link to={to} className={classes} aria-label={ariaLabel} onClick={onClick}>
        {body}
      </Link>
    );
  }

  if (href) {
    return (
      <a href={href} className={classes} aria-label={ariaLabel} onClick={onClick}>
        {body}
      </a>
    );
  }

  if (onClick) {
    return (
      <button type="button" className={cn(classes, "w-full")} aria-label={ariaLabel} onClick={onClick}>
        {body}
      </button>
    );
  }

  return (
    <div className={classes} aria-label={ariaLabel}>
      {body}
    </div>
  );
}

export interface GlowCardGridProps {
  children: ReactNode;
  /** Tailwind cols override. Default: 1 → 3 on sm+. */
  className?: string;
}

/** Responsive grid for a row of `GlowCard`s. */
export function GlowCardGrid({ children, className }: GlowCardGridProps) {
  return (
    <div className={cn("grid grid-cols-1 sm:grid-cols-3 gap-2.5", className)}>
      {children}
    </div>
  );
}
