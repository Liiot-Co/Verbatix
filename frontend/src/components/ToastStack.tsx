import { AnimatePresence, motion } from "framer-motion";
import { createPortal } from "react-dom";
import { CheckCircle2, XCircle, Info, X } from "lucide-react";
import { useWizardStore as useAppStore } from "@/store/useWizardStore";

const ICONS = {
  success: <CheckCircle2 className="w-4 h-4 text-p-success shrink-0" />,
  error:   <XCircle      className="w-4 h-4 text-p-error   shrink-0" />,
  info:    <Info         className="w-4 h-4 text-p-accent   shrink-0" />,
};

function Stack() {
  const toasts      = useAppStore((s) => s.toasts);
  const dismissToast = useAppStore((s) => s.dismissToast);

  return (
    <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 pointer-events-none">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div
            key={t.id}
            initial={{ opacity: 0, x: 20, scale: 0.96 }}
            animate={{ opacity: 1, x: 0,  scale: 1    }}
            exit={{    opacity: 0, x: 20,  scale: 0.96 }}
            transition={{ type: "spring", stiffness: 320, damping: 28 }}
            className="pointer-events-auto card px-4 py-3 flex items-center gap-3 min-w-[260px] max-w-xs"
          >
            {ICONS[t.type]}
            <span className="text-sm text-p-text flex-1">{t.message}</span>
            {t.onAction && (
              <button
                onClick={() => {
                  t.onAction?.();
                  dismissToast(t.id);
                }}
                className="text-xs font-semibold text-p-accent hover:underline shrink-0"
              >
                {t.actionLabel ?? "Deshacer"}
              </button>
            )}
            <button
              onClick={() => dismissToast(t.id)}
              className="text-p-text-faint hover:text-p-text transition-colors"
              aria-label="Cerrar"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

export default function ToastStack() {
  return createPortal(<Stack />, document.body);
}
