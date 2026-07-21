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
    label: "Exacto aprobado",
    className: "badge-auto",
    hint: "Coincidió exactamente con una memoria aprobada o una regla cerrada.",
  },
  suggested: {
    label: "Sugerido",
    className: "badge-warning",
    hint: "El motor encontró un candidato, pero necesita confirmación humana.",
  },
  garbage: {
    label: "Basura probable",
    className: "badge-error",
    hint: "Texto vacío, ilegible o sin contenido clasificable; requiere confirmación.",
  },
  engine_error: {
    label: "Error del motor",
    className: "badge-error",
    hint: "La clasificación técnica falló; no se interpretó como anomalía del dato.",
  },
  abstained: {
    label: "Abstención",
    className: "badge-warning",
    hint: "DeepSeek no encontró evidencia suficiente para proponer una decisión segura.",
  },
  conflict: {
    label: "Conflicto",
    className: "badge-error",
    hint: "Existe evidencia aprobada contradictoria y debe adjudicarse manualmente.",
  },
  resolved: {
    label: "Resuelto",
    className: "badge-success",
    hint: "Ya tiene un código asignado, manual o automático.",
  },
};
