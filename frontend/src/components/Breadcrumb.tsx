import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";

export interface Crumb {
  label: string;
  /** Route to navigate to (full page nav). */
  to?: string;
  /** In-page navigation (e.g. jump to a wizard step) — takes precedence over `to`. */
  onClick?: () => void;
}

export default function Breadcrumb({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="Ruta de navegación" className="flex items-center gap-1 text-xs">
      {items.map((item, i) => {
        const isLast = i === items.length - 1;
        const showLink = item.to && !isLast;
        const showButton = item.onClick && !isLast && !item.to;
        return (
          <span key={i} className="flex items-center gap-1">
            {showLink ? (
              <Link to={item.to!} className="text-p-text-muted hover:text-p-text transition-colors">
                {item.label}
              </Link>
            ) : showButton ? (
              <button onClick={item.onClick} className="text-p-text-muted hover:text-p-text transition-colors">
                {item.label}
              </button>
            ) : (
              <span className={isLast ? "text-p-text font-medium" : "text-p-text-muted"}>{item.label}</span>
            )}
            {!isLast && <ChevronRight className="w-3 h-3 text-p-text-faint" />}
          </span>
        );
      })}
    </nav>
  );
}
