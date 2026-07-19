import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { markNotificationRead } from "@/api/client";
import type { NotificationPreview } from "@/api/types";
import { NOTIFICATION_META, notificationPath } from "@/lib/notificationPresentation";
import { useNotificationStore } from "@/store/useNotificationStore";

function NotificationToastStack() {
  const toasts = useNotificationStore((state) => state.toasts);
  const dismissToast = useNotificationStore((state) => state.dismissToast);
  const reducedMotion = useReducedMotion();
  const navigate = useNavigate();

  const open = async (toastId: number, notification: NotificationPreview) => {
    dismissToast(toastId);
    if (!notification.is_read) void markNotificationRead(notification.id).catch(() => {});
    const path = notificationPath(notification);
    if (path) navigate(path);
  };

  return (
    <div className="fixed top-4 right-4 z-toast flex w-full max-w-sm flex-col gap-2 pointer-events-none" aria-live="polite">
      <AnimatePresence initial={false}>
        {toasts.map((toast) => {
          const { Icon, chipClass } = NOTIFICATION_META[toast.notification.type];
          return (
            <motion.div
              key={toast.id}
              layout={!reducedMotion}
              initial={reducedMotion ? { opacity: 0 } : { opacity: 0, x: 30, scale: 0.97 }}
              animate={reducedMotion ? { opacity: 1 } : { opacity: 1, x: 0, scale: 1 }}
              exit={reducedMotion ? { opacity: 0 } : { opacity: 0, x: 30, scale: 0.97 }}
              transition={reducedMotion ? { duration: 0.16 } : { type: "spring", stiffness: 350, damping: 25, mass: 0.8 }}
              className="pointer-events-auto overflow-hidden rounded-2xl border border-p-border bg-p-surface shadow-xl"
            >
              <div className="flex w-full items-start gap-1 px-2 pt-2 pb-1">
                <button onClick={() => void open(toast.id, toast.notification)} className="flex min-w-0 flex-1 gap-3 px-2 py-1 text-left active:scale-[0.99]">
                  <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${chipClass}`}><Icon className="h-4 w-4" /></span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-semibold text-p-text">{toast.notification.title}</span>
                    {toast.notification.body && <span className="mt-0.5 block text-xs leading-relaxed text-p-text-muted">{toast.notification.body}</span>}
                    {toast.notification.sender_name && <span className="mt-1 block text-[11px] font-medium text-p-text-muted">Enviado por {toast.notification.sender_name}</span>}
                  </span>
                </button>
                <button
                  onClick={() => dismissToast(toast.id)}
                  className="rounded-md p-1 text-p-text-faint hover:bg-p-bg-subtle hover:text-p-text"
                  aria-label="Cerrar notificación"
                ><X className="h-3.5 w-3.5" />
                </button>
              </div>
              <motion.div
                className="h-0.5 origin-left bg-p-accent"
                initial={{ scaleX: 1 }}
                animate={reducedMotion ? { scaleX: 1 } : { scaleX: 0 }}
                transition={{ duration: 5, ease: "linear" }}
              />
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}

export default function NotificationToast() {
  return createPortal(<NotificationToastStack />, document.body);
}
