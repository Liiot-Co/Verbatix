import { useState } from "react";
import { Check, X, Users, AlertTriangle } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import type { DuplicateFlag } from "@/api/types";

interface DuplicatesReviewTableProps {
  duplicates: DuplicateFlag[];
  onResolve: (flag: { flag_id: string }, action: "keep" | "remove", kind: "duplicate") => Promise<void>;
  onBulkResolve: (action: "keep" | "remove") => Promise<void>;
}

export default function DuplicatesReviewTable({ duplicates, onResolve, onBulkResolve }: DuplicatesReviewTableProps) {
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [bulkAction, setBulkAction] = useState<"keep" | "remove" | null>(null);

  const pendingCount = duplicates.filter((d) => d.status === "pending").length;
  const isResolved = pendingCount === 0;

  const handleResolve = async (flagId: string, action: "keep" | "remove") => {
    if (resolvingId) return;
    setResolvingId(flagId);
    try {
      await onResolve({ flag_id: flagId }, action, "duplicate");
    } finally {
      setResolvingId(null);
    }
  };

  const handleBulk = async (action: "keep" | "remove") => {
    if (bulkAction) return;
    if (!confirm(`¿Seguro que deseas ${action === "keep" ? "mantener" : "descartar"} todos los registros nuevos pendientes?`)) return;
    setBulkAction(action);
    try {
      await onBulkResolve(action);
    } finally {
      setBulkAction(null);
    }
  };

  return (
    <div className="card border-p-border bg-white shadow-sm overflow-hidden flex flex-col max-h-[600px]">
      <div className="p-4 border-b border-p-border flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-p-surface shrink-0">
        <div className="flex items-center gap-2">
          <div className={`p-1.5 rounded-md ${isResolved ? "bg-p-success/10 text-p-success" : "bg-p-warning/10 text-p-warning"}`}>
            {isResolved ? <Check className="w-4 h-4" /> : <Users className="w-4 h-4" />}
          </div>
          <div>
            <h2 className="text-sm font-bold text-p-text flex items-center gap-2">
              Posibles duplicados reales
              <span className={`text-[10px] uppercase font-bold px-1.5 py-0.5 rounded-full ${isResolved ? "bg-p-success text-white" : "bg-p-warning text-white"}`}>
                {isResolved ? "Resueltos" : `${pendingCount} Pendientes`}
              </span>
            </h2>
            <p className="text-xs text-p-text-muted mt-0.5">
              El mismo ID real (persona) ya existe en otra carga de esta ronda.
            </p>
          </div>
        </div>
        
        {!isResolved && (
          <div className="flex gap-2 shrink-0">
            <button
              onClick={() => void handleBulk("keep")}
              disabled={!!bulkAction || !!resolvingId}
              className="btn-secondary text-xs py-1.5 px-3 flex items-center gap-1.5"
            >
              <Check className="w-3.5 h-3.5 text-p-success" />
              {bulkAction === "keep" ? "Procesando..." : "Mantener todos"}
            </button>
            <button
              onClick={() => void handleBulk("remove")}
              disabled={!!bulkAction || !!resolvingId}
              className="btn-danger text-xs py-1.5 px-3 flex items-center gap-1.5"
            >
              <X className="w-3.5 h-3.5" />
              {bulkAction === "remove" ? "Procesando..." : "Descartar nuevos"}
            </button>
          </div>
        )}
      </div>

      <div className="overflow-auto bg-p-bg-subtle p-0 relative">
        <table className="w-full text-left text-sm whitespace-nowrap">
          <thead className="sticky top-0 bg-p-surface shadow-[0_1px_2px_rgba(0,0,0,0.05)] z-10">
            <tr>
              <th className="px-4 py-3 font-semibold text-p-text-muted text-xs uppercase tracking-wider">ID Real</th>
              <th className="px-4 py-3 font-semibold text-p-text-muted text-xs uppercase tracking-wider border-l border-p-border/50">Carga Actual (Nuevo)</th>
              <th className="px-4 py-3 font-semibold text-p-text-muted text-xs uppercase tracking-wider border-l border-p-border/50">Cargas Anteriores</th>
              <th className="px-4 py-3 font-semibold text-p-text-muted text-xs uppercase tracking-wider border-l border-p-border/50 w-[200px] text-center">Acción</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-p-border/50 bg-white">
            <AnimatePresence initial={false}>
              {duplicates.map((flag) => {
                const isPending = flag.status === "pending";
                const isWorking = resolvingId === flag.flag_id || bulkAction;
                return (
                  <motion.tr 
                    key={flag.flag_id}
                    layout
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className={`transition-colors ${isPending ? "hover:bg-p-accent-soft/30" : "bg-p-surface/50 text-p-text-muted"}`}
                  >
                    <td className="px-4 py-3">
                      <code className="px-1.5 py-0.5 bg-p-bg-subtle rounded text-xs font-semibold border border-p-border">
                        {flag.realid ?? "—"}
                      </code>
                    </td>
                    <td className="px-4 py-3 border-l border-p-border/50">
                      <div className="flex items-center gap-2">
                        {isPending && <AlertTriangle className="w-3.5 h-3.5 text-p-warning shrink-0" />}
                        <span className={isPending ? "font-semibold text-p-text" : "line-through text-p-text-faint"}>
                          Serial {flag.serial ?? "—"}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 border-l border-p-border/50">
                      <div className="flex flex-col gap-1">
                        {flag.matches.map((m, i) => (
                          <div key={i} className="flex items-center gap-1.5 text-xs">
                            <span className="font-medium text-p-text">Serial {m.serial ?? "—"}</span>
                            <span className="text-p-text-faint">en</span>
                            <span className="px-1.5 py-0.5 bg-p-surface rounded border border-p-border truncate max-w-[150px]" title={m.source_label}>
                              {m.source_label}
                            </span>
                          </div>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-2 border-l border-p-border/50 text-center">
                      {isPending ? (
                        <div className="flex items-center justify-center gap-1.5">
                          <button
                            onClick={() => void handleResolve(flag.flag_id, "keep")}
                            disabled={!!isWorking}
                            className="btn-ghost text-xs px-2 py-1 flex items-center gap-1 hover:text-p-success hover:bg-p-success/10"
                            title="Mantener Ambos"
                          >
                            <Check className="w-3.5 h-3.5" />
                          </button>
                          <div className="w-px h-4 bg-p-border" />
                          <button
                            onClick={() => void handleResolve(flag.flag_id, "remove")}
                            disabled={!!isWorking}
                            className="btn-ghost text-xs px-2 py-1 flex items-center gap-1 hover:text-p-error hover:bg-p-error/10"
                            title="Descartar Nuevo"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      ) : (
                        <span className={`text-[10px] uppercase font-bold px-2 py-1 rounded-full ${
                          flag.status === "approved_keep" ? "bg-p-success/10 text-p-success" : 
                          flag.status === "approved_remove" ? "bg-p-error/10 text-p-error" : 
                          "bg-p-accent/10 text-p-accent"
                        }`}>
                          {flag.status === "approved_keep" ? "Ambos" : flag.status === "approved_remove" ? "Descartado" : "Editado"}
                        </span>
                      )}
                    </td>
                  </motion.tr>
                );
              })}
            </AnimatePresence>
            {duplicates.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-sm text-p-text-muted">
                  No se encontraron duplicados reales.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
