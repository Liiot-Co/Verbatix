import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Loader2, Zap } from "lucide-react";
import { useAppStore } from "@/store/useAppStore";
import { resolveAnomaly } from "@/api/client";
import EntityCard from "@/components/EntityCard";

/* Cascade flash banner */
function CascadeBanner({ count, brand }: { count: number; brand: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      className="card-subtle px-4 py-3 flex items-center gap-2 text-sm border-p-accent/30 bg-p-accent/5"
    >
      <Zap className="w-4 h-4 text-p-accent shrink-0" />
      <span>
        <span className="font-semibold text-p-accent">{count}</span> respuestas similares a{" "}
        <span className="font-semibold text-p-text">"{brand}"</span> resueltas automáticamente
      </span>
    </motion.div>
  );
}

export default function Step2Review() {
  const items          = useAppStore((s) => s.items);
  const resolveItems   = useAppStore((s) => s.resolveItems);
  const uploadResult   = useAppStore((s) => s.uploadResult);
  const setStep        = useAppStore((s) => s.setStep);
  const showToast      = useAppStore((s) => s.showToast);
  const focusedIdx     = useAppStore((s) => s.focusedItemIdx);
  const setFocusedIdx  = useAppStore((s) => s.setFocusedItemIdx);

  const [resolving, setResolving]   = useState<number | null>(null);
  const [cascade, setCascade]       = useState<{ count: number; brand: string } | null>(null);

  const pending = items.filter((i) => i.status === "requires_human");
  const total   = uploadResult?.requires_human ?? pending.length;
  const done    = total - pending.length;
  const progress = total > 0 ? done / total : 0;

  /* ↑↓ navigation */
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "ArrowDown") { e.preventDefault(); setFocusedIdx(Math.min(focusedIdx + 1, pending.length - 1)); }
      if (e.key === "ArrowUp")   { e.preventDefault(); setFocusedIdx(Math.max(focusedIdx - 1, 0)); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [focusedIdx, pending.length, setFocusedIdx]);

  const resolve = useCallback(async (responseId: number, brand: string) => {
    setResolving(responseId);
    try {
      const result = await resolveAnomaly({ response_id: responseId, resolved_brand: brand });
      resolveItems(result.resolved, result.cascade_resolved);

      if (result.cascade_resolved.length > 0) {
        setCascade({ count: result.cascade_resolved.length, brand });
        setTimeout(() => setCascade(null), 4000);
        showToast(`+${result.cascade_resolved.length} resueltos en cascada`, "success");
      } else {
        showToast(`"${brand}" guardado`, "success");
      }

      setFocusedIdx(Math.max(0, Math.min(focusedIdx, pending.length - 2)));
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Error al resolver", "error");
    } finally {
      setResolving(null);
    }
  }, [resolveItems, showToast, setFocusedIdx, pending.length]);

  const handleApprove = useCallback((item: typeof pending[0]) => {
    if (!item.suggested_brand) return;
    resolve(item.id, item.suggested_brand);
  }, [resolve]);

  const handleReject = useCallback(async (responseId: number) => {
    setResolving(responseId);
    try {
      const result = await resolveAnomaly({ response_id: responseId, resolved_brand: "__rejected__" });
      resolveItems(result.resolved, []);
      showToast("Rechazado", "info");
    } catch {
      showToast("Error al rechazar", "error");
    } finally {
      setResolving(null);
    }
  }, [resolveItems, showToast]);

  if (items.length === 0) {
    return (
      <div className="text-center py-20 space-y-4">
        <p className="text-p-text-muted text-sm">Sin datos. Sube un archivo primero.</p>
        <button onClick={() => setStep(1)} className="btn-ghost text-sm">← Paso 1</button>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-p-text tracking-tight">Revisa las marcas</h1>
          <p className="text-sm text-p-text-muted">
            Paso 2 — {pending.length} {pending.length === 1 ? "respuesta requiere" : "respuestas requieren"} validación
          </p>
        </div>
        <button onClick={() => setStep(3)} className="btn-primary shrink-0 text-sm">
          Ver Dashboard →
        </button>
      </div>

      {/* Progress */}
      <div className="card-subtle px-4 py-3 space-y-2">
        <div className="flex justify-between text-xs text-p-text-muted">
          <span>{done} de {total} resueltos</span>
          <span className="font-mono">{Math.round(progress * 100)}%</span>
        </div>
        <div className="h-1 rounded-full bg-p-bg-subtle overflow-hidden">
          <motion.div
            className="h-full rounded-full bg-gradient-to-r from-p-accent to-p-accent-mid"
            animate={{ width: `${progress * 100}%` }}
            transition={{ duration: 0.4, ease: "easeOut" }}
          />
        </div>
      </div>

      {/* Cascade banner */}
      <AnimatePresence>
        {cascade && <CascadeBanner count={cascade.count} brand={cascade.brand} />}
      </AnimatePresence>

      {/* Cards */}
      <AnimatePresence mode="popLayout">
        {pending.length > 0 ? (
          pending.map((item, idx) => (
            <EntityCard
              key={item.id}
              item={item}
              focused={focusedIdx === idx && resolving === null}
              onFocus={() => setFocusedIdx(idx)}
              onApprove={() => handleApprove(item)}
              onReject={() => handleReject(item.id)}
              onEdit={(brand) => resolve(item.id, brand)}
            />
          ))
        ) : (
          <motion.div
            key="done"
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            className="card p-10 text-center space-y-3"
          >
            <p className="text-2xl">✓</p>
            <p className="font-semibold text-p-text">Cola completada</p>
            <p className="text-sm text-p-text-muted">Todas las respuestas fueron resueltas.</p>
            <button onClick={() => setStep(3)} className="btn-primary text-sm mx-auto">
              Ir al Dashboard →
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {resolving !== null && (
        <div className="fixed bottom-6 right-6 card px-4 py-2 flex items-center gap-2 text-sm shadow-lg">
          <Loader2 className="w-4 h-4 animate-spin text-p-accent" />
          <span className="text-p-text-muted">Guardando y verificando cascada...</span>
        </div>
      )}
    </div>
  );
}
