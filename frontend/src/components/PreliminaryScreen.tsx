import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { AlertTriangle, ArrowRight, CheckCircle2, PartyPopper, RefreshCw } from "lucide-react";
import { getPreliminary, getStudio, processStudio } from "@/api/client";
import type { PreliminarySummary, StudioStatus } from "@/api/types";
import Breadcrumb from "./Breadcrumb";
import { useVerbatixStore } from "@/store/useVerbatixStore";

export default function PreliminaryScreen() {
  const { studioId } = useParams<{ studioId: string }>();
  const showToast = useVerbatixStore((s) => s.showToast);

  const [studio, setStudio] = useState<StudioStatus | null>(null);
  const [preliminary, setPreliminary] = useState<PreliminarySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);

  const refresh = () => {
    if (!studioId) return Promise.resolve();
    return Promise.all([getStudio(studioId), getPreliminary(studioId)]).then(([s, p]) => {
      setStudio(s);
      setPreliminary(p);
    });
  };

  useEffect(() => {
    setLoading(true);
    refresh().finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studioId]);

  const handleProcess = async () => {
    if (!studioId) return;
    setProcessing(true);
    try {
      const result = await processStudio(studioId);
      showToast(
        `${result.groups_classified} grupos codificados solos, ${result.anomalies} necesitan revisión`,
        "success"
      );
      await refresh();
    } catch {
      showToast("No se pudo procesar el estudio", "error");
    } finally {
      setProcessing(false);
    }
  };

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto py-4 space-y-4">
        <div className="skeleton h-6 w-40 rounded" />
        <div className="skeleton h-40 rounded-2xl" />
      </div>
    );
  }

  if (!studio || !preliminary) {
    return (
      <div className="max-w-3xl mx-auto py-4">
        <p className="text-sm text-p-text-faint">Estudio no encontrado.</p>
      </div>
    );
  }

  const { auto_coded, pending_review, anomalies, resolved } = preliminary.summary;
  const total = auto_coded + pending_review + anomalies + resolved;
  const codedPct = total ? Math.round(((auto_coded + resolved) / total) * 100) : 0;
  const hasPending = pending_review > 0;
  const neverProcessed = hasPending && auto_coded + resolved === 0;
  const justFinished = total > 0 && codedPct === 100;

  const momentum =
    codedPct === 100
      ? "¡Todo codificado! El motor resolvió el 100% solo."
      : codedPct >= 75
      ? "Casi listo — el motor va muy bien."
      : codedPct >= 40
      ? "Buen avance, sigue así."
      : codedPct > 0
      ? "Arrancando — el motor ya empezó a codificar."
      : "Sin codificar todavía.";

  return (
    <div className="max-w-3xl mx-auto py-4 space-y-6">
      <Breadcrumb items={[{ label: "Proyectos", to: "/" }, { label: studio.name }]} />

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="space-y-1">
          <h1 className="font-heading text-2xl font-semibold text-p-text tracking-tight">{studio.name}</h1>
          <p className="font-subtitle text-sm text-p-text-muted">
            {studio.coding_type === "brands" ? "Marcas" : "Razones"} · {studio.counters.verbatims_total} verbatims · estado: {studio.status}
          </p>
        </div>
        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className={neverProcessed ? "btn-primary text-sm py-2" : "btn-ghost text-sm py-2"}
          disabled={processing}
          onClick={handleProcess}
          title={neverProcessed ? "Codificar automáticamente" : "Volver a correr el motor sobre lo pendiente"}
        >
          {processing ? (
            <motion.span
              animate={{ rotate: 360 }}
              transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
              className="w-4 h-4 border-2 border-current/30 border-t-current rounded-full"
            />
          ) : (
            <RefreshCw className="w-4 h-4" />
          )}
          {processing ? "Procesando..." : neverProcessed ? "Procesar" : "Reprocesar"}
        </motion.button>
      </div>

      {/* Momentum + progress bar */}
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

      {/* Two columns: codificado / pendiente */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="card p-4 space-y-2">
          <div className="flex items-center gap-2 text-p-success">
            <CheckCircle2 className="w-4 h-4" />
            <span className="text-xs font-semibold uppercase tracking-wide">Codificado</span>
          </div>
          <div className="text-2xl font-bold text-p-text">{auto_coded + resolved}</div>
          <p className="text-xs text-p-text-faint">Grupos que el motor resolvió solo (o ya fueron revisados).</p>
        </div>
        <div className="card p-4 space-y-2">
          <div className="flex items-center gap-2 text-p-warning">
            <AlertTriangle className="w-4 h-4" />
            <span className="text-xs font-semibold uppercase tracking-wide">Pendiente</span>
          </div>
          <div className="text-2xl font-bold text-p-text">{pending_review + anomalies}</div>
          <p className="text-xs text-p-text-faint">
            {pending_review} sin procesar todavía · {anomalies} menciones confusas
          </p>
        </div>
      </div>

      <div className="flex justify-end">
        <Link
          to={`/studios/${studio.id}/verbatims`}
          className="flex items-center gap-1 text-sm text-p-accent hover:underline hover:translate-x-0.5 transition-transform"
        >
          Ver verbatims <ArrowRight className="w-3.5 h-3.5" />
        </Link>
      </div>

      {!hasPending && anomalies > 0 && (
        <p className="text-center text-xs text-p-text-faint">
          Nada sin procesar. Quedan {anomalies} anomalías por revisar a mano.
        </p>
      )}
    </div>
  );
}
