import type { MentionGroupStatus } from "@/api/types";

export const STATUS_CHIP: Record<MentionGroupStatus, { label: string; className: string; hint: string }> = {
  anomaly: {
    label: "Confusa",
    className: "badge-error",
    hint: "El motor no encontró un código con suficiente confianza — necesita una decisión humana.",
  },
  below_threshold: {
    label: "Bajo umbral",
    className: "badge-warning",
    hint: "Hay una sugerencia, pero su confianza no alcanza el umbral automático del estudio.",
  },
  pending_review: {
    label: "Sin revisar",
    className: "badge-pending",
    hint: "Todavía no fue procesada por el motor de codificación.",
  },
  auto_coded: {
    label: "Sugerido",
    className: "badge-auto",
    hint: "El motor asignó un código automáticamente con alta confianza.",
  },
  resolved: {
    label: "Resuelto",
    className: "badge-success",
    hint: "Ya tiene un código asignado, manual o automático.",
  },
};
