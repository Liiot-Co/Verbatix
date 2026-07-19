import { createPortal } from "react-dom";
import { useEffect, useLayoutEffect, useState, type RefObject } from "react";
import { BellOff, CheckCheck, ChevronRight, Inbox } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { getNotifications, getUnreadCount, markAllNotificationsRead, markNotificationRead } from "@/api/client";
import type { Notification } from "@/api/types";
import { NOTIFICATION_META, notificationPath, relativeNotificationTime } from "@/lib/notificationPresentation";
import { useNotificationStore } from "@/store/useNotificationStore";

interface NotificationsPanelProps {
  anchorRef: RefObject<HTMLDivElement | null>;
  onClose: () => void;
}

export default function NotificationsPanel({ anchorRef, onClose }: NotificationsPanelProps) {
  const navigate = useNavigate();
  const items = useNotificationStore((state) => state.items);
  const setItems = useNotificationStore((state) => state.setItems);
  const setStreamState = useNotificationStore((state) => state.setStreamState);
  const muted = useNotificationStore((state) => state.muted);
  const toggleMuted = useNotificationStore((state) => state.toggleMuted);
  const [loading, setLoading] = useState(items.length === 0);
  const [position, setPosition] = useState<{ left: number; bottom: number } | null>(null);

  const refresh = async () => {
    const [list, state] = await Promise.all([getNotifications(8), getUnreadCount()]);
    setItems(list.items);
    setStreamState({ unread: state.unread_count, signal: state.signal });
  };

  useEffect(() => {
    void refresh().finally(() => setLoading(false));
  }, []);

  // El sidebar recorta su contenido para el layout. Este panel es un popover:
  // se renderiza en document.body, pero conserva el anclaje espacial de la campana.
  useLayoutEffect(() => {
    const updatePosition = () => {
      const rect = anchorRef.current?.getBoundingClientRect();
      if (!rect) return;
      setPosition({
        left: Math.max(8, Math.min(rect.left, window.innerWidth - 360)),
        bottom: Math.max(8, window.innerHeight - rect.top + 8),
      });
    };
    updatePosition();
    window.addEventListener("resize", updatePosition);
    document.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      document.removeEventListener("scroll", updatePosition, true);
    };
  }, [anchorRef]);

  const open = async (notification: Notification) => {
    if (!notification.is_read) {
      await markNotificationRead(notification.id).catch(() => {});
      await refresh().catch(() => {});
    }
    onClose();
    const path = notificationPath(notification);
    if (path) navigate(path);
  };

  const readAll = async () => {
    await markAllNotificationsRead();
    await refresh();
  };

  if (!position) return null;

  return createPortal(
    <div
      className="fixed z-[60] w-[min(22rem,calc(100vw-1rem))] overflow-hidden rounded-2xl border border-p-border bg-p-surface shadow-xl"
      style={position}
      role="dialog"
      aria-label="Notificaciones"
      onMouseDown={(event) => event.stopPropagation()}
    >
      <div className="flex items-center justify-between border-b border-p-border px-4 py-3">
        <div><h2 className="text-sm font-semibold text-p-text">Notificaciones</h2><p className="text-[11px] text-p-text-muted">Mantente al día sin interrumpir tu flujo.</p></div>
        <button onClick={() => void readAll()} className="rounded-lg px-2 py-1 text-[11px] font-medium text-p-accent hover:bg-p-accent/10" title="Marcar todas como leídas"><CheckCheck className="mr-1 inline h-3.5 w-3.5" />Leer todas</button>
      </div>
      <div className="max-h-[23rem] overflow-y-auto">
        {loading ? <p className="px-4 py-8 text-center text-xs text-p-text-muted">Cargando…</p> : items.length === 0 ? (
          <div className="px-4 py-9 text-center"><Inbox className="mx-auto mb-2 h-6 w-6 text-p-text-faint" /><p className="text-xs text-p-text-muted">Todo está al día.</p></div>
        ) : items.map((notification) => {
          const { Icon, chipClass } = NOTIFICATION_META[notification.type];
          return <button key={notification.id} onClick={() => void open(notification)} className={`flex w-full gap-3 px-4 py-3 text-left transition-colors hover:bg-p-bg-subtle ${notification.is_read ? "" : "bg-p-accent/[0.035]"}`}>
            <span className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${chipClass}`}><Icon className="h-3.5 w-3.5" /></span>
            <span className="min-w-0 flex-1"><span className="flex items-center gap-2"><span className="truncate text-xs font-semibold text-p-text">{notification.title}</span>{!notification.is_read && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-p-accent" />}</span><span className="mt-0.5 line-clamp-2 block text-[11px] leading-relaxed text-p-text-muted">{notification.body}</span>{notification.sender_name && <span className="mt-1 block text-[10px] font-medium text-p-text-muted">Enviado por {notification.sender_name}</span>}<span className="mt-1 block text-[10px] text-p-text-faint">{relativeNotificationTime(notification.last_reminded_at ?? notification.created_at)}</span></span>
          </button>;
        })}
      </div>
      <div className="flex items-center justify-between border-t border-p-border p-2">
        <button onClick={toggleMuted} className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[11px] text-p-text-muted hover:bg-p-bg-subtle"><BellOff className="h-3.5 w-3.5" />{muted ? "Activar sonido" : "Silenciar"}</button>
        <button onClick={() => { onClose(); navigate("/notifications"); }} className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-[11px] font-medium text-p-accent hover:bg-p-accent/10">Ver todas <ChevronRight className="h-3.5 w-3.5" /></button>
      </div>
    </div>,
    document.body,
  );
}
