import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { motion } from "framer-motion";
import { AlertTriangle, ArrowRight, CheckCircle2, PlayCircle } from "lucide-react";
import { getPreliminary, getStudio, processStudio } from "@/api/client";
import type { PreliminarySummary, StudioStatus } from "@/api/types";
import Breadcrumb from "./Breadcrumb";
import { useVerbatixStore } from "@/store/useVerbatixStore";

export default function PreliminaryScreen() {
  const { studioId } = useParams<{ studioId: string }>();
  const navigate = useNavigate();
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
        `El motor propuso ${result.groups_classified} grupos, ${result.anomalies} quedaron como anomalías`,
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
          className="btn-primary text-sm py-2"
          disabled={processing}
          onClick={handleProcess}
        >
          {processing ? (
            <motion.span
              animate={{ rotate: 360 }}
              transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
              className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full"
            />
          ) : (
            <PlayCircle className="w-4 h-4" />
          )}
          {processing ? "Procesando..." : "Procesar"}
        </motion.button>
      </div>

      {/* Progress bar */}
      <div className="card p-4 space-y-2">
        <div className="flex items-center justify-between text-xs text-p-text-muted">
          <span>Avance del motor</span>
          <span className="font-semibold text-p-text">{codedPct}%</span>
        </div>
        <div className="h-2 rounded-full bg-p-bg-subtle overflow-hidden">
          <motion.div
            className="h-full bg-gradient-to-r from-p-accent to-p-accent-mid"
            initial={{ width: 0 }}
            animate={{ width: `${codedPct}%` }}
            transition={{ duration: 0.5, ease: [0.19, 1, 0.22, 1] as const }}
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
        <motion.button
          whileHover={{ x: 2 }}
          className="flex items-center gap-1 text-sm text-p-accent hover:underline"
          onClick={() => navigate(`/studios/${studio.id}/verbatims`)}
        >
          Ver verbatims <ArrowRight className="w-3.5 h-3.5" />
        </motion.button>
      </div>

      {!hasPending && total > 0 && (
        <p className="text-center text-xs text-p-text-faint">
          No quedan grupos sin procesar. La resolución manual de anomalías es el siguiente paso (Fase 3).
        </p>
      )}
    </div>
  );
}
