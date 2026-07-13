import { AlertTriangle, CheckCircle2, PartyPopper } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import type { PreliminarySummary } from "@/api/types";

interface StudioSummaryCardsProps {
  summary: PreliminarySummary["summary"] | undefined;
  momentum: string;
  codedPct: number;
  justFinished: boolean;
  /** Abre el Centro de Resolución en fullscreen. */
  onOpenResolution: () => void;
}

export function StudioSummaryCards({
  summary,
  momentum,
  codedPct,
  justFinished,
  onOpenResolution,
}: StudioSummaryCardsProps) {
  const autoCoded = summary?.auto_coded ?? 0;
  const pendingReview = summary?.pending_review ?? 0;
  const anomalies = summary?.anomalies ?? 0;
  const resolved = summary?.resolved ?? 0;

  return (
    <>
      <div className="card p-4 space-y-2">
        <div className="flex items-center justify-between text-xs text-p-text-muted">
          <span className="flex items-center gap-1.5">
            <AnimatePresence mode="wait">
              {justFinished && (
                <motion.span
                  key="party"
                  initial={{ scale: 0, rotate: -20 }}
                  animate={{ scale: 1, rotate: 0 }}
                  transition={{ type: "spring", stiffness: 400, damping: 15 }}
                >
                  <PartyPopper className="w-3.5 h-3.5 text-p-success" />
                </motion.span>
              )}
            </AnimatePresence>
            {momentum}
          </span>
          <span className="font-semibold text-p-text">{codedPct}%</span>
        </div>
        <div className="h-2 rounded-full bg-p-bg-subtle overflow-hidden">
          <motion.div
            className={[
              "h-full bg-gradient-to-r",
              justFinished ? "from-p-success to-p-success" : "from-p-accent to-p-accent-mid",
            ].join(" ")}
            initial={{ width: 0 }}
            animate={{ width: `${codedPct}%` }}
            transition={{ duration: 0.6, ease: [0.19, 1, 0.22, 1] as const }}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="card p-4 space-y-2">
          <div className="flex items-center gap-2 text-p-success">
            <CheckCircle2 className="w-4 h-4" />
            <span className="text-xs font-semibold uppercase tracking-wide">Codificado</span>
          </div>
          <div className="text-2xl font-bold text-p-text">{autoCoded + resolved}</div>
          <p className="text-xs text-p-text-faint">Grupos que el motor resolvió solo (o ya fueron revisados).</p>
        </div>
        <button
          type="button"
          onClick={onOpenResolution}
          className="card p-4 space-y-2 block text-left w-full hover:border-p-warning/50 transition-colors"
        >
          <div className="flex items-center gap-2 text-p-warning">
            <AlertTriangle className="w-4 h-4" />
            <span className="text-xs font-semibold uppercase tracking-wide">Pendiente</span>
          </div>
          <div className="text-2xl font-bold text-p-text">{pendingReview + anomalies}</div>
          <p className="text-xs text-p-text-faint">
            {pendingReview} sin procesar todavía · {anomalies} menciones confusas — ir al Centro de Resolución
          </p>
        </button>
      </div>
    </>
  );
}
