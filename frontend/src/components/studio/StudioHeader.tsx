import { Link } from "react-router-dom";
import { RefreshCw, BarChart3 } from "lucide-react";
import { motion } from "framer-motion";
import type { RoundStatus } from "@/api/types";
import { hasReportAccess, studyDisplayName } from "@/lib/projectTree";
import { studioStatusLabel } from "@/lib/studioStatus";

interface StudioHeaderProps {
  studio: RoundStatus;
  autoProcessing: boolean;
  neverProcessed: boolean;
  isProcessingNow: boolean;
  onProcess: () => void;
}

export function StudioHeader({
  studio,
  autoProcessing,
  neverProcessed,
  isProcessingNow,
  onProcess,
}: StudioHeaderProps) {
  const title = studyDisplayName(studio.study_name, studio.coding_type);

  return (
    <div className="flex items-start justify-between gap-4 flex-wrap">
      <div className="space-y-1">
        <h1 className="font-heading text-2xl font-semibold text-p-text tracking-tight">{title}</h1>
        <p className="font-subtitle text-sm text-p-text-muted">
          {studio.counters.verbatims_total} verbatims · estado: {studioStatusLabel(studio.status)}
        </p>
      </div>
      <div className="flex items-center gap-2">
        {hasReportAccess(studio.status) && (
          <Link
            to={`/rounds/${studio.id}/report`}
            className="btn-ghost text-sm py-2 inline-flex items-center gap-1.5"
          >
            <BarChart3 className="w-4 h-4" />
            Ver reporte
          </Link>
        )}
        {autoProcessing && (
          <span className="flex items-center gap-1.5 text-xs text-p-accent">
            <motion.span
              animate={{ opacity: [1, 0.3, 1] }}
              transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
              className="w-2 h-2 rounded-full bg-p-accent"
            />
            En vivo
          </span>
        )}
        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className={neverProcessed ? "btn-primary text-sm py-2" : "btn-ghost text-sm py-2"}
          disabled={isProcessingNow}
          onClick={onProcess}
          title={
            autoProcessing
              ? "El motor ya está codificando en segundo plano"
              : neverProcessed
              ? "Codificar automáticamente"
              : "Volver a correr el motor sobre lo pendiente"
          }
        >
          {isProcessingNow ? (
            <motion.span
              animate={{ rotate: 360 }}
              transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
              className="w-4 h-4 border-2 border-current/30 border-t-current rounded-full"
            />
          ) : (
            <RefreshCw className="w-4 h-4" />
          )}
          {isProcessingNow ? "Procesando..." : neverProcessed ? "Procesar" : "Reprocesar"}
        </motion.button>
      </div>
    </div>
  );
}
