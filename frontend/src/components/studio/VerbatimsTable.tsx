import type { VerbatimSummaryRow } from "@/api/types";

interface VerbatimsTableProps {
  loading: boolean;
  rows: VerbatimSummaryRow[];
  search: string;
}

export function VerbatimsTable({ loading, rows, search }: VerbatimsTableProps) {
  return (
    <div className="card overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-p-border text-left">
            <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">Código</th>
            <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">Mención principal</th>
            <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">Contenido</th>
            <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider text-right">Frecuencia</th>
            <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider text-right">%</th>
          </tr>
        </thead>
        <tbody>
          {loading ? (
            Array.from({ length: 6 }).map((_, i) => (
              <tr key={`skeleton-${i}`} className="border-b border-p-border last:border-0">
                <td className="px-4 py-2.5"><div className="skeleton h-3 w-10 rounded" /></td>
                <td className="px-4 py-2.5"><div className="skeleton h-3 w-32 rounded" /></td>
                <td className="px-4 py-2.5"><div className="skeleton h-3 w-3/4 rounded" /></td>
                <td className="px-4 py-2.5"><div className="skeleton h-3 w-10 rounded ml-auto" /></td>
                <td className="px-4 py-2.5"><div className="skeleton h-3 w-10 rounded ml-auto" /></td>
              </tr>
            ))
          ) : rows.length === 0 ? (
            <tr>
              <td colSpan={5} className="px-4 py-8 text-center text-p-text-faint text-sm">
                {search ? `Sin resultados para "${search}".` : "Nada por aquí todavía."}
              </td>
            </tr>
          ) : (
            rows.map((r, i) => (
              <tr
                key={r.code_id ?? `${r.content}-${i}`}
                className="border-b border-p-border last:border-0 hover:bg-p-bg-subtle/50 transition-colors duration-100"
              >
                <td className="px-4 py-2.5 text-p-text-faint text-xs whitespace-nowrap">{r.code_number ?? "—"}</td>
                <td className="px-4 py-2.5 text-p-text font-medium max-w-xs">
                  <span className="block truncate">{r.label ?? "—"}</span>
                </td>
                <td className="px-4 py-2.5 text-p-text max-w-sm">
                  <div className="tooltip-trigger w-full">
                    <span className="block truncate">{r.content ?? "—"}</span>
                    {r.content && <div className="tooltip whitespace-normal break-words max-w-xl">{r.content}</div>}
                  </div>
                </td>
                <td className="px-4 py-2.5 text-p-text-muted text-xs text-right tabular-nums">{r.frequency}</td>
                <td className="px-4 py-2.5 text-p-text-muted text-xs text-right tabular-nums">{r.percentage}%</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
