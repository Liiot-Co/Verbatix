import { AnimatePresence, motion } from "framer-motion";
import { createPortal } from "react-dom";
import { CheckCircle2, XCircle, Info, X } from "lucide-react";
import { useVerbatixStore } from "@/store/useVerbatixStore";

const ICONS = {
  success: <CheckCircle2 className="w-4 h-4 text-p-success shrink-0" />,
  error:   <XCircle      className="w-4 h-4 text-p-error   shrink-0" />,
  info:    <Info         className="w-4 h-4 text-p-accent   shrink-0" />,
};

function Stack() {
  const toasts       = useVerbatixStore((s) => s.toasts);
  const dismissToast = useVerbatixStore((s) => s.dismissToast);

  return (
    <div
      className="fixed top-4 right-4 z-toast flex flex-col gap-2 pointer-events-none max-w-xs w-full"
      data-close-on-escape
    >
      <AnimatePresence>
        {toasts.map((t, i) => (
          <motion.div
            key={t.id}
            layout
            initial={{ opacity: 0, x: 40, scale: 0.95, y: -10 }}
            animate={{ opacity: 1, x: 0, scale: 1, y: 0 }}
            exit={{ opacity: 0, x: 40, scale: 0.9, y: -5 }}
            transition={{
              type: "spring",
              stiffness: 350,
              damping: 25,
              mass: t.type === "error" ? 1.2 : 0.8,
              delay: i * 0.05,
            }}
            className="pointer-events-auto card px-4 py-3 flex items-center gap-3 min-w-[260px] shadow-lg"
          >
            {ICONS[t.type]}
            <span className="text-sm text-p-text flex-1">{t.message}</span>
            {t.onAction && (
              <motion.button
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                onClick={() => {
                  t.onAction?.();
                  dismissToast(t.id);
                }}
                className="text-xs font-semibold text-p-accent hover:underline shrink-0"
              >
                {t.actionLabel ?? "Deshacer"}
              </motion.button>
            )}
            <motion.button
              whileHover={{ scale: 1.1, color: "oklch(var(--p-text))" }}
              whileTap={{ scale: 0.9 }}
              onClick={() => dismissToast(t.id)}
              className="text-p-text-faint transition-colors shrink-0"
              aria-label="Cerrar"
            >
              <X className="w-3.5 h-3.5" />
            </motion.button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

export default function ToastStack() {
  return createPortal(<Stack />, document.body);
}