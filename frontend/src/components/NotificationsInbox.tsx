import { useEffect, useMemo, useState } from "react";
import { Bell, CheckCheck, Inbox, LoaderCircle } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { getNotifications, getUnreadCount, markAllNotificationsRead, markNotificationRead } from "@/api/client";
import type { Notification } from "@/api/types";
import { NOTIFICATION_META, notificationPath, relativeNotificationTime } from "@/lib/notificationPresentation";
import { useNotificationStore } from "@/store/useNotificationStore";

const PAGE_SIZE = 20;
const FILTERS: Array<{ value: boolean; label: string }> = [{ value: false, label: "Todas" }, { value: true, label: "No leídas" }];

function dayLabel(value: string): string {
  const date = new Date(value);
  const today = new Date();
  const startToday = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
  const startDate = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  if (startDate === startToday) return "Hoy";
  if (startDate === startToday - 86400000) return "Ayer";
  return date.toLocaleDateString("es-CO", { weekday: "long", day: "numeric", month: "long" });
}

export default function NotificationsInbox() {
  const navigate = useNavigate();
  const setStreamState = useNotificationStore((state) => state.setStreamState);
  const [onlyUnread, setOnlyUnread] = useState(false);
  const [items, setItems] = useState<Notification[]>([]);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  const load = async (nextOffset = 0, append = false) => {
    setLoading(true);
    try {
      const [list, state] = await Promise.all([getNotifications(PAGE_SIZE, nextOffset, onlyUnread), getUnreadCount()]);
      setItems((current) => append ? [...current, ...list.items] : list.items);
      setTotal(list.total);
      setOffset(nextOffset);
      setStreamState({ unread: state.unread_count, signal: state.signal });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [onlyUnread]);

  const groups = useMemo(() => items.reduce<Record<string, Notification[]>>((acc, item) => {
    const label = dayLabel(item.created_at);
    (acc[label] ??= []).push(item);
    return acc;
  }, {}), [items]);

  const open = async (notification: Notification) => {
    if (!notification.is_read) await markNotificationRead(notification.id).catch(() => {});
    const path = notificationPath(notification);
    if (path) navigate(path);
    void load(offset);
  };

  const readAll = async () => {
    await markAllNotificationsRead();
    await load(0);
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div><div className="mb-2 flex h-10 w-10 items-center justify-center rounded-xl bg-p-accent/12 text-p-accent"><Bell className="h-5 w-5" /></div><h1 className="font-heading text-2xl font-bold tracking-tight text-p-text">Bandeja de entrada</h1><p className="mt-1 text-sm text-p-text-muted">Asignaciones y avances de auditoría en un solo lugar.</p></div>
        <button onClick={() => void readAll()} className="btn-ghost-sm self-start sm:self-auto"><CheckCheck className="h-4 w-4" />Marcar todas como leídas</button>
      </header>

      <div className="flex gap-1 rounded-xl border border-p-border bg-p-surface p-1 w-fit">
        {FILTERS.map(({ value, label }) => <button key={String(value)} onClick={() => setOnlyUnread(value)} className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${onlyUnread === value ? "bg-p-accent text-white shadow-sm" : "text-p-text-muted hover:bg-p-bg-subtle"}`}>{label}</button>)}
      </div>

      <section className="overflow-hidden rounded-2xl border border-p-border bg-p-surface shadow-card">
        {loading && items.length === 0 ? <div className="flex min-h-64 items-center justify-center"><LoaderCircle className="h-5 w-5 animate-spin text-p-accent" /></div> : items.length === 0 ? (
          <div className="px-6 py-16 text-center"><Inbox className="mx-auto mb-3 h-9 w-9 text-p-text-faint" /><h2 className="text-sm font-semibold text-p-text">No tienes notificaciones{onlyUnread ? " sin leer" : ""}</h2><p className="mt-1 text-xs text-p-text-muted">Cuando haya novedades del equipo aparecerán aquí.</p></div>
        ) : Object.entries(groups).map(([day, notifications]) => <div key={day}>
          <div className="sticky top-0 z-10 border-y border-p-border bg-p-bg-subtle/95 px-5 py-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-p-text-faint backdrop-blur">{day}</div>
          {notifications.map((notification) => {
            const { Icon, chipClass } = NOTIFICATION_META[notification.type];
            return <button key={notification.id} onClick={() => void open(notification)} className={`flex w-full gap-4 border-b border-p-border px-5 py-4 text-left transition-colors hover:bg-p-bg-subtle ${notification.is_read ? "" : "bg-p-accent/[0.035]"}`}>
              <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${chipClass}`}><Icon className="h-4 w-4" /></span>
              <span className="min-w-0 flex-1"><span className="flex items-center gap-2"><span className="text-sm font-semibold text-p-text">{notification.title}</span>{!notification.is_read && <span className="h-1.5 w-1.5 rounded-full bg-p-accent" />}</span><span className="mt-1 block text-xs leading-relaxed text-p-text-muted">{notification.body}</span>{notification.sender_name && <span className="mt-1.5 block text-[11px] font-medium text-p-text-muted">Enviado por {notification.sender_name}</span>}<span className="mt-2 block text-[11px] text-p-text-faint">{relativeNotificationTime(notification.last_reminded_at ?? notification.created_at)}</span></span>
            </button>;
          })}
        </div>)}
      </section>
      {items.length < total && <div className="text-center"><button disabled={loading} onClick={() => void load(offset + PAGE_SIZE, true)} className="btn-ghost-sm">{loading ? "Cargando…" : "Cargar más"}</button></div>}
    </div>
  );
}
