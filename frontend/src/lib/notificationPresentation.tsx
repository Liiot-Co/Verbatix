import { ClipboardCheck, ShieldCheck, UserPlus, type LucideIcon } from "lucide-react";
import type { Notification, NotificationType } from "@/api/types";

export const NOTIFICATION_META: Record<NotificationType, {
  Icon: LucideIcon;
  chipClass: string;
}> = {
  project_assigned: { Icon: UserPlus, chipClass: "bg-p-accent/12 text-p-accent" },
  ready_for_audit: { Icon: ClipboardCheck, chipClass: "bg-p-warning/15 text-p-warning" },
  audit_approved: { Icon: ShieldCheck, chipClass: "bg-p-success/15 text-p-success" },
};

export function notificationPath(notification: Notification): string | null {
  if (!notification.related_entity_id) return null;
  if (notification.type === "project_assigned") return `/projects/${notification.related_entity_id}`;
  if (notification.type === "ready_for_audit") return `/rounds/${notification.related_entity_id}/audit`;
  return `/rounds/${notification.related_entity_id}/report`;
}

export function relativeNotificationTime(value: string): string {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return "Ahora";
  if (seconds < 3600) return `Hace ${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `Hace ${Math.floor(seconds / 3600)} h`;
  if (seconds < 172800) return "Ayer";
  return new Date(value).toLocaleDateString("es-CO", { day: "numeric", month: "short" });
}
