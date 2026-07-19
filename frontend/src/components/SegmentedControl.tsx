export interface SegmentedControlOption<T extends string> {
  value: T;
  label: string;
}

interface SegmentedControlProps<T extends string> {
  name: string;
  options: SegmentedControlOption<T>[];
  // null = sin selección (p.ej. Excel, donde no hay sugerencia de coding_type).
  value: T | null;
  onChange: (value: T) => void;
  ariaLabel?: string;
}

export default function SegmentedControl<T extends string>({
  name,
  options,
  value,
  onChange,
  ariaLabel,
}: SegmentedControlProps<T>) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel ?? name}
      className="inline-flex gap-1 rounded-xl border border-p-border bg-p-surface p-1 w-fit"
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <label
            key={option.value}
            className={[
              "cursor-pointer rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
              active ? "bg-p-accent text-white shadow-sm" : "text-p-text-muted hover:bg-p-bg-subtle",
            ].join(" ")}
          >
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={active}
              onChange={() => onChange(option.value)}
              className="sr-only"
            />
            {option.label}
          </label>
        );
      })}
    </div>
  );
}
