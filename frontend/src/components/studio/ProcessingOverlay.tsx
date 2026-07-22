import { motion, AnimatePresence } from "framer-motion";
import { Upload, Cpu, Sparkles, Network, CheckCircle2, PartyPopper } from "lucide-react";

type StageId = "uploaded" | "processing" | "coding_started" | "coding_progress" | "coding_almost" | "complete";

const STAGES = [
  { id: "uploaded", icon: Upload, label: "Preparando" },
  { id: "processing", icon: Cpu, label: "Iniciando motor" },
  { id: "coding_started", icon: Sparkles, label: "Estructurando" },
  { id: "coding_progress", icon: Network, label: "Agrupando" },
  { id: "coding_almost", icon: CheckCircle2, label: "Ajustando" },
  { id: "complete", icon: PartyPopper, label: "Listo" },
] as const;

function getStage(status: string | undefined, effectivePct: number): StageId {
  if (effectivePct === 100) return "complete";
  if (effectivePct >= 75) return "coding_almost";
  if (effectivePct >= 40) return "coding_progress";
  if (effectivePct > 0) return "coding_started";
  if (status === "processing") return "processing";
  if (status === "files_uploaded") return "uploaded";
  return "processing";
}

interface CounterItem {
  label: string;
  value: number;
  color: string;
}

interface ProcessingOverlayProps {
  visible: boolean;
  status: string | undefined;
  codedPct: number;
  autoCoded: number;
  pendingReview: number;
  anomalies: number;
  resolved: number;
  pollCount?: number;
}

export default function ProcessingOverlay({
  visible,
  status,
  codedPct,
  autoCoded,
  pendingReview,
  anomalies,
  resolved,
  pollCount = 0,
}: ProcessingOverlayProps) {
  const totalCoded = autoCoded + resolved;
  const totalPending = pendingReview + anomalies;
  const total = totalCoded + totalPending;
  // When real coded-group data is available, use it directly.
  // While the engine is still starting (total=0, codedPct=0), drive a smooth
  // asymptotic fake-progress from pollCount so the bar isn't frozen at 0%.
  // Each poll is ~8 s; the curve approaches 88% but never reaches it, so it
  // never looks "done" before the real data arrives.
  const fakeProgress = total === 0 && codedPct === 0 && pollCount > 0
    ? Math.round(88 * (1 - Math.exp(-pollCount / 6)))
    : null;
  const progress = total > 0 ? Math.round((totalCoded / total) * 100) : (fakeProgress ?? codedPct);
  const stageId = getStage(status, progress);
  const isComplete = stageId === "complete";
  const activeIndex = STAGES.findIndex(s => s.id === stageId);

  const counters: CounterItem[] = [
    { label: "Codificados", value: totalCoded, color: "text-p-success" },
    { label: isComplete ? "Revisados" : "Pendientes", value: totalPending, color: isComplete ? "text-p-success" : "text-p-warning" },
  ];
  if (anomalies > 0 && !isComplete) {
    counters.push({ label: "Anomalías", value: anomalies, color: "text-p-error" });
  }

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          key="processing-overlay"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.3 }}
          className="absolute inset-0 z-20 flex items-center justify-center p-4 bg-p-surface/60 backdrop-blur-sm"
        >
          <motion.div
            initial={{ opacity: 0, y: 16, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -16, scale: 0.95 }}
            transition={{ type: "spring", stiffness: 400, damping: 30 }}
            className="flex flex-col items-center gap-8 px-10 py-12 max-w-2xl w-full bg-p-surface border border-p-border/50 shadow-2xl rounded-3xl"
          >
            <div className="text-center space-y-2">
              <h2 className="text-lg font-semibold text-p-text">Procesando con Verbatix Engine</h2>
              {!isComplete && (
                <p className="text-sm text-p-text-muted flex items-center justify-center gap-2">
                  <motion.span
                    className="w-1.5 h-1.5 rounded-full bg-p-accent"
                    animate={{ opacity: [1, 0.3, 1] }}
                    transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
                  />
                  {pollCount > 0 ? `Analizando datos (actualización ${pollCount})...` : "Iniciando análisis..."}
                </p>
              )}
            </div>

            {/* Stepper horizontal */}
            <div className="w-full flex justify-between items-center relative px-2">
              <div className="absolute left-8 right-8 top-1/2 -translate-y-1/2 h-0.5 bg-p-border -z-10" />
              {STAGES.map((stage, idx) => {
                const Icon = stage.icon;
                const isPassed = idx < activeIndex;
                const isActive = idx === activeIndex;
                
                let iconBg = "bg-p-surface border-p-border text-p-text-faint";
                if (isActive) {
                  iconBg = isComplete 
                    ? "bg-p-success border-p-success text-white shadow-lg shadow-p-success/30"
                    : "bg-p-accent border-p-accent text-white shadow-lg shadow-p-accent/30";
                } else if (isPassed) {
                  iconBg = "bg-p-success border-p-success text-white";
                }

                return (
                  <div key={stage.id} className="flex flex-col items-center gap-3 bg-p-surface px-2">
                    <motion.div
                      initial={false}
                      animate={{ scale: isActive ? 1.15 : 1 }}
                      className={`relative w-10 h-10 rounded-full flex items-center justify-center border-2 transition-colors duration-500 ${iconBg}`}
                    >
                      <Icon className={`w-4 h-4 ${isActive && !isComplete ? "animate-pulse" : ""}`} />
                      {isActive && !isComplete && (
                        <motion.div
                          className="absolute inset-0 rounded-full border border-p-accent"
                          animate={{ scale: [1, 1.5], opacity: [0.8, 0] }}
                          transition={{ duration: 1.5, repeat: Infinity, ease: "easeOut" }}
                        />
                      )}
                    </motion.div>
                    <span className={`text-[11px] font-medium transition-colors duration-500 ${isActive ? "text-p-accent" : isPassed ? "text-p-success" : "text-p-text-faint"}`}>
                      {stage.label}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Progress bar and details */}
            <div className="w-full space-y-4">
              <div className="space-y-2">
                <div className="flex justify-between text-xs font-medium">
                  <span className={isComplete ? "text-p-success" : "text-p-text"}>Avance general</span>
                  <span className={isComplete ? "text-p-success" : "text-p-text-muted"}>{progress}%</span>
                </div>
                <div className="h-2 rounded-full bg-p-bg-subtle overflow-hidden">
                  <motion.div
                    className={`h-full rounded-full ${isComplete ? "bg-p-success" : "bg-[linear-gradient(to_right,#5A228B,#FF4D6D,#FF6A33,#FFC300)]"}`}
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.min(progress, 100)}%` }}
                    transition={{ duration: 0.7, ease: [0.19, 1, 0.22, 1] }}
                  />
                </div>
              </div>
              
              {/* Counters */}
              {total > 0 && (
                <motion.div
                  className="flex gap-6 justify-center pt-2"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                >
                  {counters.map((c) => (
                    <div key={c.label} className="flex flex-col items-center">
                      <motion.span
                        key={`${c.label}-${c.value}`}
                        className={`text-lg font-semibold tabular-nums ${c.color}`}
                        initial={{ scale: 1.3, opacity: 0.5 }}
                        animate={{ scale: 1, opacity: 1 }}
                        transition={{ type: "spring", stiffness: 400, damping: 20 }}
                      >
                        {c.value}
                      </motion.span>
                      <span className="text-xs text-p-text-faint">{c.label}</span>
                    </div>
                  ))}
                </motion.div>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

