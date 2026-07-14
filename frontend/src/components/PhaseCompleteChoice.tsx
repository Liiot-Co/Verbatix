import { useNavigate } from "react-router-dom";
import { ArrowRight, ClipboardCheck, Sparkles } from "lucide-react";
import { motion } from "framer-motion";

interface PhaseCompleteChoiceProps {
  studioId: string;
  /** Overlay centrado (modal) o barra inline. */
  variant?: "modal" | "inline";
  onDismiss?: () => void;
}

/** Tras cerrar la resolución manual: continuar al reporte o auditar (opcional). */
export function PhaseCompleteChoice({
  studioId,
  variant = "inline",
  onDismiss,
}: PhaseCompleteChoiceProps) {
  const navigate = useNavigate();

  const goReport = () => {
    onDismiss?.();
    navigate(`/studios/${studioId}/report`);
  };

  const goAudit = () => {
    onDismiss?.();
    navigate(`/studios/${studioId}/audit`);
  };

  const card = (
    <div className="glow-card glow-card-3 p-5 sm:p-6 space-y-4">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-xl bg-p-success/15 flex items-center justify-center shrink-0">
          <Sparkles className="w-5 h-5 text-p-success" />
        </div>
        <div className="space-y-1 min-w-0">
          <h2 className="font-heading text-lg font-semibold text-p-text tracking-tight">
            Resolución completa
          </h2>
          <p className="text-sm text-p-text-muted">
            Todos los grupos pendientes fueron revisados. Puedes ir al resultado final o auditar
            una muestra (opcional).
          </p>
        </div>
      </div>
      <div className="flex flex-col sm:flex-row gap-2 sm:justify-end">
        <button type="button" className="btn-ghost text-sm py-2 order-2 sm:order-1" onClick={goAudit}>
          <ClipboardCheck className="w-4 h-4" />
          Auditar
        </button>
        <button type="button" className="btn-primary text-sm py-2 order-1 sm:order-2" onClick={goReport}>
          Continuar al reporte
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );

  if (variant === "modal") {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-p-text/20 backdrop-blur-[2px]">
        <motion.div
          initial={{ opacity: 0, scale: 0.96, y: 8 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          className="w-full max-w-lg"
        >
          {card}
        </motion.div>
      </div>
    );
  }

  return card;
}
