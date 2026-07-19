import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ClipboardCheck,
  Clock3,
  MessageSquare,
  Pencil,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Trash2,
} from "lucide-react";
import { motion } from "framer-motion";
import {
  approveAudit,
  approveAuditSection,
  ApiError,
  createAuditSession,
  deleteAuditItem,
  deleteAuditComment,
  editAuditComment,
  getAuditCodes,
  getAuditReadiness,
  getAuditItems,
  getRound,
  getRoundCodes,
  patchAuditItem,
  reviewAuditItem,
} from "@/api/client";
import type {
  AuditCodeReview,
  AuditItem,
  AuditReadiness,
  AuditSessionSummary,
  CodingType,
  RoundCode,
  RoundStatus,
} from "@/api/types";
import { registerShortcuts, useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { playSuccess, playTick } from "@/lib/sound";
import { useVerbatixStore } from "@/store/useVerbatixStore";
import { can } from "@/lib/capabilities";
import Breadcrumb from "./Breadcrumb";

const ITEMS_PAGE = 200;

const ITEM_CHIP: Record<AuditItem["status"], { label: string; className: string }> = {
  pending: { label: "Sin revisar", className: "badge-pending" },
  correct: { label: "Correcto", className: "badge-success" },
  reassigned: { label: "Corregido", className: "badge-warning" },
};

const REVIEW_CHIP: Record<AuditCodeReview["status"], { label: string; className: string }> = {
  pending: { label: "Pendiente", className: "badge-pending" },
  approved: { label: "Aprobado", className: "badge-success" },
  with_corrections: { label: "Con correcciones", className: "badge-warning" },
};

// Mismo color estable por código que usa ResolutionSidebar.
function codeColor(codeNumber: number): string {
  const hue = (codeNumber * 47) % 360;
  return `oklch(0.55 0.14 ${hue})`;
}

/**
 * Vista de Auditoría (Fase 5) — master-detail coherente con el Centro de
 * Resolución: lista de códigos muestreados a la izquierda, tabla de verbatims
 * del código seleccionado a la derecha. La revisión es POR SECCIÓN: el analista
 * corrige (reasigna/elimina/comenta) lo que esté mal y aprueba la sección — los
 * items sin corregir quedan correctos. Al completar las secciones, aprueba la
 * auditoría.
 */
export default function AuditView() {
  const { roundId } = useParams<{ roundId: string }>();
  const navigate = useNavigate();
  const showToast = useVerbatixStore((s) => s.showToast);
  const user = useVerbatixStore((s) => s.user);
  const canApprove = can(user, "audit.approve");
  const canManageRound = can(user, "rounds.manage");

  const [studio, setStudio] = useState<RoundStatus | null>(null);
  const [activeSubprojectId, setActiveSubprojectId] = useState<string | null>(null);
  const [summary, setSummary] = useState<AuditSessionSummary | null>(null);
  const [reviews, setReviews] = useState<AuditCodeReview[]>([]);
  const [codes, setCodes] = useState<RoundCode[]>([]);
  const [selectedReviewId, setSelectedReviewId] = useState<string | null>(null);
  const [items, setItems] = useState<AuditItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [blockedReason, setBlockedReason] = useState<string | null>(null);
  const [readiness, setReadiness] = useState<AuditReadiness | null>(null);
  const [waitingForCoding, setWaitingForCoding] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const [busy, setBusy] = useState(false);

  const [focusIndex, setFocusIndex] = useState(0);
  const [reassignItemId, setReassignItemId] = useState<string | null>(null);
  const [reassignCodeId, setReassignCodeId] = useState("");
  const [newCodeLabel, setNewCodeLabel] = useState("");
  const [commentItemId, setCommentItemId] = useState<string | null>(null);
  const [commentDraft, setCommentDraft] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const commentInputRef = useRef<HTMLInputElement>(null);

  const activeSubproject = studio?.subprojects.find((subproject) => subproject.id === activeSubprojectId)
    ?? studio?.subprojects.find((subproject) => subproject.coding_type === "brands")
    ?? studio?.subprojects[0];
  const codingType: CodingType = activeSubproject?.coding_type ?? "brands";
  const noun = codingType === "reasons" ? "razón" : "marca";

  const loadReviews = useCallback(async (sid: string) => {
    const list = await getAuditCodes(sid);
    setReviews(list);
    return list;
  }, []);

  // Bootstrap: primero consulta la disponibilidad global de la ronda. La
  // auditoría solo empieza cuando Marcas y Razones llegaron a cero pendientes.
  useEffect(() => {
    if (!roundId) return;
    let cancelled = false;
    setLoading(true);
    setBlockedReason(null);
    (async () => {
      try {
        const s = await getRound(roundId);
        if (cancelled) return;
        setStudio(s);
        const availability = await getAuditReadiness(roundId);
        if (cancelled) return;
        setReadiness(availability);
        if (!availability.ready) {
          setWaitingForCoding(true);
          setSummary(null);
          setReviews([]);
          setSelectedReviewId(null);
          return;
        }
        setWaitingForCoding(false);
        const subprojectId = activeSubprojectId
          ?? s.subprojects.find((subproject) => subproject.coding_type === "brands")?.id
          ?? s.subprojects[0]?.id;
        if (!subprojectId) {
          setBlockedReason("La ronda no tiene subproyectos para auditar.");
          return;
        }
        if (!activeSubprojectId) setActiveSubprojectId(subprojectId);
        const session = await createAuditSession(subprojectId);
        if (cancelled) return;
        setSummary(session);
        const [list] = await Promise.all([
          loadReviews(subprojectId),
          getRoundCodes(subprojectId, true).then(setCodes),
        ]);
        const firstPending = list.find((r) => r.reviewed_count < r.items_count) ?? list[0];
        if (firstPending) setSelectedReviewId(firstPending.id);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 422) {
          setWaitingForCoding(true);
          setBlockedReason(null);
        } else {
          setBlockedReason("No se pudo iniciar la auditoría.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [roundId, activeSubprojectId, loadReviews, retryKey]);

  // El supervisor puede dejar esta pantalla abierta: se habilita sola cuando
  // el codificador resuelve el último grupo.
  useEffect(() => {
    if (!roundId || !waitingForCoding) return;
    const intervalId = window.setInterval(() => {
      getAuditReadiness(roundId)
        .then((availability) => {
          setReadiness(availability);
          if (availability.ready) setRetryKey((value) => value + 1);
        })
        .catch(() => {});
    }, 6000);
    return () => window.clearInterval(intervalId);
  }, [roundId, waitingForCoding]);

  useEffect(() => {
    if (!selectedReviewId) {
      setItems([]);
      return;
    }
    setItemsLoading(true);
    getAuditItems(selectedReviewId, ITEMS_PAGE, 0)
      .then((res) => {
        setItems(res.items);
        setFocusIndex(0);
      })
      .finally(() => setItemsLoading(false));
  }, [selectedReviewId]);

  const refreshCounters = useCallback(
    (session: AuditSessionSummary) => {
      setSummary(session);
      if (activeSubprojectId) loadReviews(activeSubprojectId).catch(() => {});
    },
    [activeSubprojectId, loadReviews]
  );

  /** Actualización optimista con rollback (patrón del Centro de Resolución). */
  const applyOptimistic = useCallback(
    async (
      itemId: string,
      optimistic: Partial<AuditItem>,
      run: () => Promise<AuditSessionSummary | null>
    ) => {
      const before = items;
      setItems((list) => list.map((it) => (it.id === itemId ? { ...it, ...optimistic } : it)));
      try {
        const session = await run();
        if (session) refreshCounters(session);
      } catch {
        setItems(before);
        showToast("No se pudo guardar la revisión. Intenta de nuevo.", "error");
      }
    },
    [items, refreshCounters, showToast]
  );

  // Aprueba la SECCIÓN seleccionada: los items sin corregir pasan a 'correct'
  // de una vez — el analista no marca verbatim por verbatim.
  const handleApproveSection = useCallback(async () => {
    if (!selectedReviewId || busy || !activeSubprojectId) return;
    setBusy(true);
    try {
      const res = await approveAuditSection(selectedReviewId);
      playTick();
      setItems((list) => list.map((it) => (it.status === "pending" ? { ...it, status: "correct" } : it)));
      setSummary(res.summary);
      showToast(
        res.status === "with_corrections"
          ? "Sección aprobada con correcciones."
          : "Sección aprobada.",
        "success"
      );
      // Saltar a la siguiente sección pendiente para mantener el flujo.
      const list = await loadReviews(activeSubprojectId);
      const next = list.find((r) => r.id !== selectedReviewId && r.status === "pending");
      if (next) setSelectedReviewId(next.id);
    } catch {
      showToast("No se pudo aprobar la sección.", "error");
    } finally {
      setBusy(false);
    }
  }, [selectedReviewId, busy, activeSubprojectId, showToast, loadReviews]);

  const submitReassign = useCallback(
    (item: AuditItem) => {
      const codeId = reassignCodeId;
      const label = newCodeLabel.trim();
      if (!codeId && !label) return;
      const target = codes.find((c) => c.id === codeId);
      playTick();
      setReassignItemId(null);
      setReassignCodeId("");
      setNewCodeLabel("");
      applyOptimistic(
        item.id,
        {
          status: "reassigned",
          current_codes: target
            ? [{ code_id: target.id, code_number: target.code_number, label: target.label, source: "audit_correction" }]
            : item.current_codes,
        },
        async () => {
          const res = await reviewAuditItem(item.id, {
            action: "reassign",
            code_ids: codeId ? [codeId] : [],
            new_code: label ? { label } : null,
            expected_status: item.status,
          });
          if (res.new_code?.is_new && activeSubprojectId) {
            getRoundCodes(activeSubprojectId, true).then(setCodes).catch(() => {});
          }
          return res.summary;
        }
      );
    },
    [reassignCodeId, newCodeLabel, codes, applyOptimistic, activeSubprojectId]
  );

  const removeItem = useCallback(
    (item: AuditItem) => {
      setConfirmDeleteId(null);
      applyOptimistic(
        item.id,
        { status: "reassigned", current_codes: [], coding_status: "needs_review" },
        async () => {
          const res = await deleteAuditItem(item.id);
          return res.summary;
        }
      );
    },
    [applyOptimistic]
  );

  const submitComment = useCallback(
    (item: AuditItem) => {
      const comment = commentDraft.trim();
      setCommentItemId(null);
      setCommentDraft("");
      if (!comment) return;
      applyOptimistic(item.id, {
        comment,
        comments: [...item.comments, {
          id: `pending-${Date.now()}`, author_id: user?.id ?? null,
          author_name: user?.name ?? null, author_email: user?.email ?? null,
          roles: user?.roles ?? [], content: comment,
          created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
        }],
      }, async () => {
        await patchAuditItem(item.id, { comment });
        return null;
      });
    },
    [commentDraft, applyOptimistic, user]
  );

  const handleApprove = useCallback(async () => {
    if (!canApprove || !activeSubprojectId || !summary || busy) return;
    setBusy(true);
    try {
      const res = await approveAudit(activeSubprojectId);
      setSummary(res);
      playSuccess();
      const refreshedRound = await getRound(roundId!);
      setStudio(refreshedRound);
      const allApproved = refreshedRound.subprojects.every((subproject) => subproject.audit?.status === "approved");
      if (allApproved) {
        showToast("Auditoría completa — la ronda quedó auditada.", "success");
        navigate(`/rounds/${roundId}/report`, { replace: true });
      } else {
        showToast("Subproyecto auditado. Selecciona el otro tipo para completar la ronda.", "success");
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "";
      showToast(
        message.includes("422") ? "Aún no alcanzaste la muestra objetivo." : "No se pudo aprobar la auditoría.",
        "error"
      );
    } finally {
      setBusy(false);
    }
  }, [roundId, activeSubprojectId, summary, busy, showToast, navigate, canApprove]);

  const handleResample = useCallback(async () => {
    if (!activeSubprojectId || busy) return;
    setBusy(true);
    try {
      const session = await createAuditSession(activeSubprojectId, true);
      setSummary(session);
      const list = await loadReviews(activeSubprojectId);
      setSelectedReviewId(list[0]?.id ?? null);
      showToast("Muestra regenerada con el último procesamiento.", "success");
    } catch {
      showToast("No se pudo re-muestrear.", "error");
    } finally {
      setBusy(false);
    }
  }, [activeSubprojectId, busy, loadReviews, showToast]);

  const focusedItem = items[focusIndex] ?? null;
  const approved = summary?.status === "approved";

  useEffect(() => {
    registerShortcuts("audit-view", [
      {
        key: "ArrowDown",
        action: () => setFocusIndex((i) => Math.min(items.length - 1, i + 1)),
        description: "Siguiente verbatim",
        category: "Navegación",
      },
      {
        key: "ArrowUp",
        action: () => setFocusIndex((i) => Math.max(0, i - 1)),
        description: "Verbatim anterior",
        category: "Navegación",
      },
      {
        key: "a",
        action: () => canApprove && !approved && handleApproveSection(),
        description: "Aprobar sección",
        category: "Acciones",
      },
      {
        key: "r",
        action: () => {
          if (!focusedItem || approved) return;
          setReassignItemId((id) => (id === focusedItem.id ? null : focusedItem.id));
        },
        description: `Reasignar ${noun}`,
        category: "Acciones",
      },
      {
        key: "e",
        action: () => {
          if (!focusedItem || approved) return;
          setCommentItemId(focusedItem.id);
          setCommentDraft(focusedItem.comment ?? "");
          setTimeout(() => commentInputRef.current?.focus(), 60);
        },
        description: "Editar comentario",
        category: "Acciones",
      },
      {
        key: "x",
        action: () => focusedItem && !approved && setConfirmDeleteId(focusedItem.id),
        description: "Eliminar asignación",
        category: "Acciones",
      },
      {
        key: "Escape",
        action: () => {
          setReassignItemId(null);
          setCommentItemId(null);
          setConfirmDeleteId(null);
        },
        description: "Cerrar paneles",
        category: "Navegación",
      },
    ]);
  }, [items.length, focusedItem, approved, handleApproveSection, noun]);

  useKeyboardShortcuts("audit-view");

  const selectedReview = useMemo(
    () => reviews.find((r) => r.id === selectedReviewId) ?? null,
    [reviews, selectedReviewId]
  );

  if (!roundId) return null;

  if (loading) {
    return (
      <div className="max-w-6xl mx-auto py-4 space-y-4">
        <div className="skeleton h-6 w-40 rounded" />
        <div className="skeleton h-16 rounded-2xl" />
        <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4">
          <div className="skeleton h-72 rounded-2xl" />
          <div className="skeleton h-72 rounded-2xl" />
        </div>
      </div>
    );
  }

  const auditBreadcrumbs = [
    { label: "Proyectos", to: "/" },
    ...(studio ? [{ label: studio.project_name, to: `/projects/${studio.project_id}` }] : []),
    ...(studio ? [{ label: studio.name, to: `/rounds/${roundId}` }] : []),
    { label: "Auditoría" },
  ];

  if (waitingForCoding) {
    const pending = readiness?.pending ?? 0;
    return (
      <div className="max-w-5xl mx-auto py-4 space-y-4">
        <Breadcrumb items={auditBreadcrumbs} />
        <div className="card relative overflow-hidden border-p-accent/20">
          <motion.div
            className="absolute -top-24 -right-20 w-72 h-72 rounded-full bg-p-accent/10 blur-3xl pointer-events-none"
            animate={{ scale: [1, 1.12, 1], opacity: [0.45, 0.8, 0.45] }}
            transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
          />
          <motion.div
            className="absolute -bottom-28 -left-20 w-72 h-72 rounded-full bg-p-success/10 blur-3xl pointer-events-none"
            animate={{ scale: [1.1, 0.95, 1.1], opacity: [0.35, 0.65, 0.35] }}
            transition={{ duration: 6, repeat: Infinity, ease: "easeInOut" }}
          />

          <div className="relative px-6 py-10 sm:px-10 sm:py-12 text-center">
            <div className="relative w-20 h-20 mx-auto mb-5">
              <motion.div
                className="absolute inset-0 rounded-full border border-p-accent/30"
                animate={{ scale: [1, 1.35], opacity: [0.8, 0] }}
                transition={{ duration: 2.2, repeat: Infinity, ease: "easeOut" }}
              />
              <div className="absolute inset-2 rounded-2xl bg-p-accent-soft flex items-center justify-center shadow-sm">
                <Clock3 className="w-8 h-8 text-p-accent" />
              </div>
              <Sparkles className="absolute -right-1 top-0 w-5 h-5 text-p-warning" />
            </div>

            <span className="badge-warning inline-flex mb-3">Codificación en curso</span>
            <h1 className="font-heading text-2xl sm:text-3xl font-semibold text-p-text tracking-tight">
              Preparando la auditoría
            </h1>
            <p className="text-sm text-p-text-muted max-w-xl mx-auto mt-3 leading-relaxed">
              El equipo de codificación está terminando los últimos grupos. La muestra de auditoría se habilitará automáticamente cuando Marcas y Razones lleguen a cero pendientes.
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 max-w-3xl mx-auto mt-8 text-left">
              <div className="rounded-xl border border-p-accent/30 bg-p-accent/5 p-4">
                <div className="flex items-center gap-2 text-p-accent font-semibold text-sm">
                  <motion.span
                    className="w-2 h-2 rounded-full bg-p-accent"
                    animate={{ opacity: [1, 0.3, 1] }}
                    transition={{ duration: 1.4, repeat: Infinity }}
                  />
                  1. Codificación
                </div>
                <p className="text-xs text-p-text-muted mt-2">
                  {pending > 0 ? `${pending} ${pending === 1 ? "grupo pendiente" : "grupos pendientes"}` : "Confirmando el cierre"}
                </p>
              </div>
              <div className="rounded-xl border border-p-border bg-p-surface/70 p-4 opacity-75">
                <div className="flex items-center gap-2 text-p-text font-semibold text-sm">
                  <ClipboardCheck className="w-4 h-4 text-p-text-faint" /> 2. Auditoría
                </div>
                <p className="text-xs text-p-text-muted mt-2">Se habilita al terminar la codificación</p>
              </div>
              <div className="rounded-xl border border-p-border bg-p-surface/70 p-4 opacity-60">
                <div className="flex items-center gap-2 text-p-text font-semibold text-sm">
                  <ShieldCheck className="w-4 h-4 text-p-text-faint" /> 3. Aprobación
                </div>
                <p className="text-xs text-p-text-muted mt-2">El supervisor cierra la revisión</p>
              </div>
            </div>

            {readiness && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-2xl mx-auto mt-5">
                {readiness.subprojects.map((subproject) => (
                  <div key={subproject.id} className="rounded-xl bg-p-bg-subtle/70 border border-p-border px-4 py-3 text-left">
                    <div className="flex items-center justify-between gap-3 text-xs">
                      <span className="font-semibold text-p-text">
                        {subproject.coding_type === "brands" ? "Marcas" : "Razones"}
                      </span>
                      <span className={subproject.ready ? "text-p-success font-semibold" : "text-p-text-muted"}>
                        {subproject.ready ? "Listo" : `${subproject.pending} pendientes`}
                      </span>
                    </div>
                    <div className="h-1.5 rounded-full bg-p-surface mt-2 overflow-hidden">
                      <motion.div
                        className={subproject.ready ? "h-full bg-p-success" : "h-full bg-p-accent"}
                        initial={{ width: 0 }}
                        animate={{ width: `${subproject.progress_pct}%` }}
                        transition={{ duration: 0.6 }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="flex flex-wrap items-center justify-center gap-3 mt-7">
              <button
                type="button"
                onClick={() => setRetryKey((value) => value + 1)}
                className="btn-primary text-sm"
              >
                <RefreshCw className="w-4 h-4" /> Comprobar ahora
              </button>
              <Link
                to={studio ? `/projects/${studio.project_id}` : "/"}
                className="btn-ghost text-sm"
              >
                Volver al proyecto
              </Link>
            </div>
            <p className="text-[11px] text-p-text-faint mt-4">Esta pantalla se actualiza automáticamente cada 6 segundos.</p>
          </div>
        </div>
      </div>
    );
  }

  if (blockedReason) {
    return (
      <div className="max-w-3xl mx-auto py-4 space-y-4">
        <Breadcrumb items={auditBreadcrumbs} />
        <div className="card p-8 text-center space-y-3">
          <AlertTriangle className="w-8 h-8 text-p-warning mx-auto" />
          <h1 className="font-heading text-xl font-semibold text-p-text">Auditoría no disponible</h1>
          <p className="text-sm text-p-text-muted">{blockedReason}</p>
          <Link to={studio ? `/projects/${studio.project_id}` : "/"} className="btn-primary inline-flex justify-center">
            Volver al proyecto
          </Link>
        </div>
      </div>
    );
  }

  if (!summary) return null;

  const progressPct = summary.total_items
    ? Math.round((summary.reviewed_items / summary.total_items) * 100)
    : 100;

  return (
    <div className="max-w-[1400px] mx-auto py-4 space-y-4">
      <Breadcrumb items={auditBreadcrumbs} />

      {studio && (
        <div className="inline-flex rounded-lg border border-p-border p-0.5">
          {studio.subprojects.map((subproject) => (
            <button
              key={subproject.id}
              type="button"
              onClick={() => setActiveSubprojectId(subproject.id)}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${activeSubproject?.id === subproject.id ? "bg-p-accent-soft text-p-accent font-medium" : "text-p-text-muted hover:text-p-text"}`}
            >
              {subproject.coding_type === "brands" ? "Marcas" : "Razones"}
            </button>
          ))}
        </div>
      )}

      {/* Header: progreso hacia el % objetivo + aprobar */}
      <div className="card p-4 space-y-3">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <ClipboardCheck className="w-5 h-5 text-p-accent" />
            <h1 className="font-heading text-2xl font-semibold text-p-text tracking-tight">Auditoría</h1>
            <span className={approved ? "badge-success" : "badge-warning"}>
              {approved ? "Auditado" : "En auditoría"}
            </span>
            {summary.is_stale && !approved && (
              <button
                onClick={handleResample}
                disabled={busy}
                className="inline-flex items-center gap-1.5 text-xs text-p-warning underline underline-offset-2"
                title="El motor volvió a procesar después del muestreo: la muestra quedó desactualizada"
              >
                <RefreshCw className="w-3.5 h-3.5" /> Muestra desactualizada — re-muestrear
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            {!approved && canManageRound && (
              <button
                type="button"
                className="btn-ghost text-sm py-2"
                onClick={() => navigate(`/rounds/${roundId}/report`)}
              >
                Ver reporte
              </button>
            )}
            {!approved && canApprove && (
            <motion.button
              whileHover={{ scale: summary.target_met ? 1.02 : 1 }}
              whileTap={{ scale: summary.target_met ? 0.98 : 1 }}
              onClick={handleApprove}
              disabled={!summary.target_met || busy}
              className="btn-primary disabled:opacity-50"
              title={summary.target_met ? "Cerrar la auditoría" : "Revisá toda la muestra para aprobar"}
            >
              <Check className="w-4 h-4" /> Aprobar auditoría
            </motion.button>
            )}
          </div>
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-xs text-p-text-muted">
            <span>
              Muestra del {summary.target_percentage}% · {summary.reviewed_items}/{summary.total_items} revisados
              {summary.items_reassigned > 0 && ` · ${summary.items_reassigned} corregidos`}
            </span>
            <span className="font-semibold text-p-text">{progressPct}%</span>
          </div>
          <div
            className="h-2 rounded-full bg-p-bg-subtle overflow-hidden"
            role="progressbar"
            aria-valuenow={progressPct}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Progreso de auditoría"
          >
            <motion.div
              className={[
                "h-full bg-gradient-to-r",
                summary.target_met ? "from-p-success to-p-success" : "from-p-accent to-p-accent-mid",
              ].join(" ")}
              initial={{ width: 0 }}
              animate={{ width: `${progressPct}%` }}
              transition={{ duration: 0.6, ease: [0.19, 1, 0.22, 1] as const }}
            />
          </div>
        </div>
      </div>

      {summary.total_items === 0 ? (
        // Muestra vacía: % en 0 o nada codificado — se puede aprobar directo.
        <div className="card p-10 text-center space-y-3">
          <CheckCircle2 className="w-8 h-8 text-p-success mx-auto" />
          <h2 className="font-heading text-lg font-semibold text-p-text">Sin muestra para auditar</h2>
          <p className="text-sm text-p-text-muted max-w-md mx-auto">
            {summary.target_percentage === 0
              ? `El % de auditoría de la ronda es 0 — no se sorteó ningún verbatim.`
              : "No hay verbatims codificados para muestrear."}{" "}
            {approved ? "La auditoría quedó aprobada." : "Podés aprobar la auditoría directamente."}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4 items-start">
          {/* Izquierda: códigos con items en la muestra */}
          <div className="card overflow-hidden flex flex-col max-h-[calc(100vh-16rem)]">
            <div className="px-4 py-2.5 border-b border-p-border text-xs font-semibold text-p-text-muted uppercase tracking-wide">
              Códigos en la muestra ({reviews.length})
            </div>
            <div className="overflow-y-auto scrollbar-thin flex-1" role="listbox" aria-label="Códigos muestreados">
              {reviews.map((r) => {
                const done = r.reviewed_count >= r.items_count;
                return (
                  <button
                    key={r.id}
                    role="option"
                    aria-selected={r.id === selectedReviewId}
                    onClick={() => setSelectedReviewId(r.id)}
                    className={[
                      "w-full text-left px-4 py-3 border-b border-p-border last:border-0 transition-colors",
                      r.id === selectedReviewId ? "bg-p-accent/10" : "hover:bg-p-bg-subtle",
                    ].join(" ")}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className="w-1.5 h-1.5 rounded-full shrink-0"
                        style={{ background: codeColor(r.code.code_number) }}
                      />
                      <span className="text-sm font-semibold text-p-text truncate flex-1">{r.code.label}</span>
                      {done && <CheckCircle2 className="w-3.5 h-3.5 text-p-success shrink-0" />}
                    </div>
                    <div className="flex items-center justify-between mt-1">
                      <span className="text-[11px] font-mono text-p-text-faint">
                        {r.reviewed_count}/{r.items_count} revisados
                      </span>
                      <span className={REVIEW_CHIP[r.status].className}>{REVIEW_CHIP[r.status].label}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Derecha: tabla del código seleccionado */}
          <div className="card overflow-hidden">
            <div className="px-4 py-2.5 border-b border-p-border flex items-center justify-between gap-2 flex-wrap">
              <span className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
                {selectedReview ? `${selectedReview.code.label} · ${selectedReview.items_count} en la muestra` : "Verbatims"}
              </span>
              <span className="flex items-center gap-2.5 font-mono text-[10px] text-p-text-faint">
                <span className="flex items-center gap-1"><kbd className="kbd-hint">↑↓</kbd>Navegar</span>
                <span className="flex items-center gap-1"><kbd className="kbd-hint">R</kbd>Reasignar</span>
                <span className="flex items-center gap-1"><kbd className="kbd-hint">E</kbd>Comentar</span>
                <span className="flex items-center gap-1"><kbd className="kbd-hint">X</kbd>Eliminar</span>
                {canApprove && <span className="flex items-center gap-1"><kbd className="kbd-hint">A</kbd>Aprobar sección</span>}
              </span>
              {/* La unidad de revisión: se aprueba la sección completa, no cada verbatim. */}
              {!approved && canApprove && selectedReview && (
                selectedReview.status === "pending" ? (
                  <motion.button
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                    onClick={handleApproveSection}
                    disabled={busy}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg project-row-icon-5 text-xs font-bold text-white hover:opacity-90 active:scale-[0.98] transition-all duration-150 disabled:opacity-50"
                  >
                    <Check className="w-3.5 h-3.5" /> Aprobar sección
                  </motion.button>
                ) : (
                  <span className={REVIEW_CHIP[selectedReview.status].className}>
                    {REVIEW_CHIP[selectedReview.status].label}
                  </span>
                )
              )}
            </div>

            {itemsLoading ? (
              <div className="p-4 space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div key={i} className="skeleton h-10 rounded" />
                ))}
              </div>
            ) : items.length === 0 ? (
              <div className="px-4 py-10 text-center text-sm text-p-text-faint">
                Este código no tiene verbatims en la muestra.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm" aria-label="Verbatims muestreados">
                  <thead>
                    <tr className="text-left text-[11px] uppercase tracking-wide text-p-text-faint border-b border-p-border">
                      <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">Respuesta</th>
                        <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">Normalizado</th>
                        <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">Código actual</th>
                        <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">Qué se hizo</th>
                        <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">Comentario</th>
                        <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider text-right">Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item, i) => (
                      <AuditRow
                        key={item.id}
                        item={item}
                        focused={i === focusIndex}
                        approved={approved}
                        codes={codes}
                        noun={noun}
                        reassignOpen={reassignItemId === item.id}
                        reassignCodeId={reassignCodeId}
                        newCodeLabel={newCodeLabel}
                        commentOpen={commentItemId === item.id}
                        commentDraft={commentDraft}
                        commentInputRef={commentInputRef}
                        confirmDelete={confirmDeleteId === item.id}
                        onFocus={() => setFocusIndex(i)}
                        onToggleReassign={() => {
                          setReassignItemId((id) => (id === item.id ? null : item.id));
                          setReassignCodeId("");
                          setNewCodeLabel("");
                        }}
                        onReassignCodeChange={setReassignCodeId}
                        onNewCodeLabelChange={setNewCodeLabel}
                        onSubmitReassign={() => submitReassign(item)}
                        onToggleComment={() => {
                          setCommentItemId((id) => (id === item.id ? null : item.id));
                          setCommentDraft("");
                          setTimeout(() => commentInputRef.current?.focus(), 60);
                        }}
                        onCommentChange={setCommentDraft}
                        onSubmitComment={() => submitComment(item)}
                        onRequestDelete={() => setConfirmDeleteId(item.id)}
                        onCancelDelete={() => setConfirmDeleteId(null)}
                        onConfirmDelete={() => removeItem(item)}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

interface AuditRowProps {
  item: AuditItem;
  focused: boolean;
  approved: boolean;
  codes: RoundCode[];
  noun: string;
  reassignOpen: boolean;
  reassignCodeId: string;
  newCodeLabel: string;
  commentOpen: boolean;
  commentDraft: string;
  commentInputRef: React.RefObject<HTMLInputElement | null>;
  confirmDelete: boolean;
  onFocus: () => void;
  onToggleReassign: () => void;
  onReassignCodeChange: (id: string) => void;
  onNewCodeLabelChange: (label: string) => void;
  onSubmitReassign: () => void;
  onToggleComment: () => void;
  onCommentChange: (comment: string) => void;
  onSubmitComment: () => void;
  onRequestDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}

function AuditRow({
  item,
  focused,
  approved,
  codes,
  noun,
  reassignOpen,
  reassignCodeId,
  newCodeLabel,
  commentOpen,
  commentDraft,
  commentInputRef,
  confirmDelete,
  onFocus,
  onToggleReassign,
  onReassignCodeChange,
  onNewCodeLabelChange,
  onSubmitReassign,
  onToggleComment,
  onCommentChange,
  onSubmitComment,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
}: AuditRowProps) {
  const currentUser = useVerbatixStore((state) => state.user);
  const chip = ITEM_CHIP[item.status];
  const removed = item.current_codes.length === 0;
  const changed =
    item.status === "reassigned" ||
    JSON.stringify(item.codes_snapshot.map((c) => c.code_id)) !==
      JSON.stringify(item.current_codes.map((c) => c.code_id));

  return (
    <>
      <tr
        onClick={onFocus}
        aria-selected={focused}
        className={[
          "border-b border-p-border last:border-0 align-top cursor-pointer transition-colors",
          focused ? "bg-p-accent/5" : "hover:bg-p-bg-subtle/60",
        ].join(" ")}
      >
        <td className="px-4 py-2.5 text-p-text max-w-[240px]">
          <span className="line-clamp-2">{item.original_text}</span>
        </td>
        <td className="px-4 py-2.5 text-p-text-muted max-w-[180px]">
          <span className="line-clamp-2">{item.normalized_text ?? "—"}</span>
        </td>
        <td className="px-4 py-2.5">
          {removed ? (
            <span className="text-xs text-p-error">Sin código</span>
          ) : (
            <div className="flex flex-wrap gap-1">
              {item.current_codes.map((c) => (
                <span
                  key={c.code_id}
                  className="chip text-xs gap-1"
                >
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: codeColor(c.code_number) }} />
                  {c.label}
                </span>
              ))}
            </div>
          )}
        </td>
        <td className="px-4 py-2.5">
          <div className="flex flex-col gap-1 items-start">
            <span className={chip.className}>{chip.label}</span>
            {changed && item.codes_snapshot.length > 0 && (
              <span className="text-[10px] text-p-text-faint" title="Códigos al momento del muestreo">
                antes: {item.codes_snapshot.map((c) => c.label).join(", ")}
              </span>
            )}
          </div>
        </td>
        <td className="px-4 py-2.5 text-xs text-p-text-muted max-w-[140px]">
          <span className="line-clamp-2">{item.comments[item.comments.length - 1]?.content ?? item.comment ?? "—"}</span>
          {item.comments.length > 1 && <span className="block text-[10px] text-p-text-faint mt-1">{item.comments.length} comentarios</span>}
        </td>
        <td className="px-4 py-2.5">
          {approved ? (
            <span className="text-[10px] text-p-text-faint">Cerrada</span>
          ) : confirmDelete ? (
            <div className="flex items-center justify-end gap-1.5">
              <button
                onClick={(e) => { e.stopPropagation(); onConfirmDelete(); }}
                className="px-2 py-1 rounded-lg border border-p-error/30 bg-p-error/10 text-xs font-bold text-p-error"
              >
                Eliminar
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); onCancelDelete(); }}
                className="px-2 py-1 rounded-lg border border-p-border text-xs text-p-text-muted"
              >
                Cancelar
              </button>
            </div>
          ) : (
            <div className="flex items-center justify-end gap-1">
              <button
                onClick={(e) => { e.stopPropagation(); onToggleReassign(); }}
                className="p-1.5 rounded-lg text-p-accent hover:bg-p-accent/10"
                title={`Reasignar ${noun} (R)`}
                aria-label="Reasignar código"
              >
                <Pencil className="w-4 h-4" />
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); onToggleComment(); }}
                className="p-1.5 rounded-lg text-p-text-muted hover:bg-p-bg-subtle"
                title="Editar comentario (E)"
                aria-label="Editar comentario"
              >
                <MessageSquare className="w-4 h-4" />
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); onRequestDelete(); }}
                disabled={removed}
                className="p-1.5 rounded-lg text-p-error hover:bg-p-error/10 disabled:opacity-30"
                title="Eliminar asignación (X)"
                aria-label="Eliminar asignación"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          )}
        </td>
      </tr>
      {(reassignOpen || commentOpen) && !approved && (
        <tr className="border-b border-p-border bg-p-bg-subtle/60">
          <td colSpan={6} className="px-4 py-3">
            {reassignOpen ? (
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
                  Reasignar a
                </span>
                <select
                  value={reassignCodeId}
                  onChange={(e) => onReassignCodeChange(e.target.value)}
                  className="input text-xs py-1 max-w-[220px]"
                  aria-label="Código destino"
                >
                  <option value="">Elegir {noun}…</option>
                  {codes.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.code_number} · {c.label}
                    </option>
                  ))}
                </select>
                <span className="text-xs text-p-text-faint">o</span>
                <input
                  type="text"
                  value={newCodeLabel}
                  onChange={(e) => onNewCodeLabelChange(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && onSubmitReassign()}
                  placeholder={`Nueva ${noun}…`}
                  className="input text-xs py-1 max-w-[200px]"
                  aria-label={`Nueva ${noun}`}
                />
                <button
                  onClick={onSubmitReassign}
                  disabled={!reassignCodeId && !newCodeLabel.trim()}
                  className="px-2.5 py-1 rounded-lg project-row-icon-2 text-xs font-bold text-white hover:opacity-90 active:scale-[0.98] transition-all duration-150 disabled:opacity-50"
                >
                  Aplicar
                </button>
                <button onClick={onToggleReassign} className="text-xs text-p-text-faint underline underline-offset-2">
                  Cancelar
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <div className="min-w-0 flex-1"><div className="text-xs font-semibold text-p-text-muted uppercase tracking-wide mb-2">Conversación</div>{item.comments.length > 0 && <div className="space-y-2 mb-3 max-h-32 overflow-auto">{item.comments.map((comment) => <div key={comment.id} className="rounded-lg bg-p-surface border border-p-border p-2"><div className="flex items-center gap-2"><div className="text-[10px] text-p-text-faint flex-1">{comment.author_name ?? comment.author_email ?? "Usuario"} · {comment.roles.join(", ")}</div>{(comment.author_id === currentUser?.id || currentUser?.roles.includes("admin")) && !comment.id.startsWith("pending-") && <><button aria-label="Editar comentario" className="text-p-text-faint hover:text-p-accent" onClick={async () => { const content = prompt("Editar comentario", comment.content)?.trim(); if (content) { await editAuditComment(comment.id, content); window.location.reload(); } }}><Pencil className="w-3 h-3" /></button><button aria-label="Eliminar comentario" className="text-p-text-faint hover:text-p-error" onClick={async () => { if (confirm("¿Eliminar este comentario?")) { await deleteAuditComment(comment.id); window.location.reload(); } }}><Trash2 className="w-3 h-3" /></button></>}</div><div className="text-xs text-p-text mt-0.5">{comment.content}</div></div>)}</div>}
                <div className="flex items-center gap-2"><span className="text-xs font-semibold text-p-text-muted">Añadir</span>
                <input
                  ref={commentInputRef}
                  type="text"
                  value={commentDraft}
                  onChange={(e) => onCommentChange(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && onSubmitComment()}
                  placeholder="Escribe un comentario…"
                  className="input text-xs py-1 flex-1 max-w-md"
                  aria-label="Comentario del item"
                />
                <button
                  onClick={onSubmitComment}
                  className="px-2.5 py-1 rounded-lg project-row-icon-2 text-xs font-bold text-white hover:opacity-90 active:scale-[0.98] transition-all duration-150"
                >
                  Publicar
                </button></div></div>
                <button onClick={onToggleComment} className="text-xs text-p-text-faint underline underline-offset-2">
                  Cancelar
                </button>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
