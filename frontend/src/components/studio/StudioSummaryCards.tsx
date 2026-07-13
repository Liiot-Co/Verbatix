import { Link } from "react-router-dom";
import { AlertTriangle, CheckCircle2, ClipboardCheck, LayoutDashboard, PartyPopper } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import type { PreliminarySummary, StudioAudit } from "@/api/types";

interface StudioSummaryCardsProps {
  studioId: string;
  summary: PreliminarySummary["summary"] | undefined;
  momentum: string;
  codedPct: number;
  justFinished: boolean;
  /** Abre el Centro de Resolución en fullscreen (flujo del pull). */
  onOpenResolution: () => void;
  /** resolution/summary.can_close — habilita el CTA "Auditar". */
  canClose: boolean;
  audit: StudioAudit | undefined;
}

const AUDIT_BADGE: Record<StudioAudit["status"], { label: string; className: string }> = {
  not_started: { label: "Sin auditar", className: "badge-pending" },
  in_progress: { label: "En auditoría", className: "badge-warning" },
  approved: { label: "Auditado", className: "badge-success" },
};

export function StudioSummaryCards({
  studioId,
  summary,
  momentum,
  codedPct,
  justFinished,
  onOpenResolution,
  canClose,
  audit,
}: StudioSummaryCardsProps) {
  const autoCoded = summary?.auto_coded ?? 0;
  const pendingReview = summary?.pending_review ?? 0;
  const anomalies = summary?.anomalies ?? 0;
  const resolved = summary?.resolved ?? 0;
  const auditBadge = AUDIT_BADGE[audit?.status ?? "not_started"];

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

      {/* Siguiente paso tras la resolución: auditar (o saltar al dashboard). */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {canClose ? (
          <Link
            to={`/studios/${studioId}/audit`}
            className="card p-4 space-y-2 block hover:border-p-accent/50 transition-colors"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-p-accent">
                <ClipboardCheck className="w-4 h-4" />
                <span className="text-xs font-semibold uppercase tracking-wide">Auditar</span>
              </div>
              <span className={auditBadge.className}>{auditBadge.label}</span>
            </div>
            <div className="text-2xl font-bold text-p-text">
              {audit && audit.total_items > 0 ? `${audit.reviewed_items}/${audit.total_items}` : "—"}
            </div>
            <p className="text-xs text-p-text-faint">
              {audit?.status === "approved"
                ? "Auditoría aprobada — el estudio quedó auditado."
                : audit?.status === "in_progress"
                ? "Auditoría en curso — continuar revisando la muestra."
                : "Revisar una muestra de lo codificado antes de cerrar."}
            </p>
          </Link>
        ) : (
          <div
            className="card p-4 space-y-2 opacity-60 cursor-not-allowed"
            title="Resolvé las anomalías pendientes primero"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-p-text-faint">
                <ClipboardCheck className="w-4 h-4" />
                <span className="text-xs font-semibold uppercase tracking-wide">Auditar</span>
              </div>
              <span className={auditBadge.className}>{auditBadge.label}</span>
            </div>
            <div className="text-2xl font-bold text-p-text-faint">—</div>
            <p className="text-xs text-p-text-faint">
              Disponible cuando no queden grupos pendientes en el Centro de Resolución.
            </p>
          </div>
        )}
        <div
          className="card p-4 space-y-2 opacity-60 cursor-not-allowed"
          title="Próximamente"
        >
          <div className="flex items-center gap-2 text-p-text-faint">
            <LayoutDashboard className="w-4 h-4" />
            <span className="text-xs font-semibold uppercase tracking-wide">Ir al dashboard</span>
          </div>
          <div className="text-2xl font-bold text-p-text-faint">—</div>
          <p className="text-xs text-p-text-faint">El dashboard llega pronto; mostrará si el estudio quedó auditado.</p>
        </div>
      </div>
    </>
  );
}
