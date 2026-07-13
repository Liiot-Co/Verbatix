import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ClipboardCheck,
  MessageSquare,
  Pencil,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { motion } from "framer-motion";
import {
  approveAudit,
  createAuditSession,
  deleteAuditItem,
  getAuditCodes,
  getAuditItems,
  getStudio,
  getStudioCodes,
  patchAuditItem,
  reviewAuditItem,
} from "@/api/client";
import type {
  AuditCodeReview,
  AuditItem,
  AuditSessionSummary,
  CodingType,
  StudioCode,
  StudioStatus,
} from "@/api/types";
import { registerShortcuts, useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { playSuccess, playTick } from "@/lib/sound";
import { useVerbatixStore } from "@/store/useVerbatixStore";
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
 * del código seleccionado a la derecha. El analista confirma, reasigna, edita
 * o elimina asignaciones hasta alcanzar el % objetivo, y aprueba.
 */
export default function AuditView() {
  const { studioId } = useParams<{ studioId: string }>();
  const showToast = useVerbatixStore((s) => s.showToast);

  const [studio, setStudio] = useState<StudioStatus | null>(null);
  const [summary, setSummary] = useState<AuditSessionSummary | null>(null);
  const [reviews, setReviews] = useState<AuditCodeReview[]>([]);
  const [codes, setCodes] = useState<StudioCode[]>([]);
  const [selectedReviewId, setSelectedReviewId] = useState<string | null>(null);
  const [items, setItems] = useState<AuditItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [blockedReason, setBlockedReason] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [focusIndex, setFocusIndex] = useState(0);
  const [reassignItemId, setReassignItemId] = useState<string | null>(null);
  const [reassignCodeId, setReassignCodeId] = useState("");
  const [newCodeLabel, setNewCodeLabel] = useState("");
  const [commentItemId, setCommentItemId] = useState<string | null>(null);
  const [commentDraft, setCommentDraft] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const commentInputRef = useRef<HTMLInputElement>(null);

  const codingType: CodingType = studio?.coding_type ?? "brands";
  const noun = codingType === "reasons" ? "razón" : "marca";

  const loadReviews = useCallback(async (sid: string) => {
    const list = await getAuditCodes(sid);
    setReviews(list);
    return list;
  }, []);

  // Bootstrap: POST crea o reanuda la sesión (idempotente) — cubre el deep-link
  // a /audit sin sesión creada. Un 422 significa resolución incompleta.
  useEffect(() => {
    if (!studioId) return;
    setLoading(true);
    (async () => {
      try {
        const [s, session] = await Promise.all([getStudio(studioId), createAuditSession(studioId)]);
        setStudio(s);
        setSummary(session);
        const [list] = await Promise.all([
          loadReviews(studioId),
          getStudioCodes(studioId, true).then(setCodes),
        ]);
        const firstPending = list.find((r) => r.reviewed_count < r.items_count) ?? list[0];
        if (firstPending) setSelectedReviewId(firstPending.id);
      } catch (err) {
        const message = err instanceof Error ? err.message : "";
        if (message.includes("422")) {
          setBlockedReason("Quedan grupos sin resolver en el Centro de Resolución.");
        } else {
          setBlockedReason("No se pudo iniciar la auditoría.");
        }
      } finally {
        setLoading(false);
      }
    })();
  }, [studioId, loadReviews]);

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
      if (studioId) loadReviews(studioId).catch(() => {});
    },
    [studioId, loadReviews]
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

  const markCorrect = useCallback(
    (item: AuditItem) => {
      if (item.status === "correct") return;
      playTick();
      applyOptimistic(item.id, { status: "correct" }, async () => {
        const res = await reviewAuditItem(item.id, { action: "correct", expected_status: item.status });
        return res.summary;
      });
    },
    [applyOptimistic]
  );

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
          if (res.new_code?.is_new && studioId) {
            getStudioCodes(studioId, true).then(setCodes).catch(() => {});
          }
          return res.summary;
        }
      );
    },
    [reassignCodeId, newCodeLabel, codes, applyOptimistic, studioId]
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
      applyOptimistic(item.id, { comment: comment || item.comment }, async () => {
        await patchAuditItem(item.id, { comment });
        return null;
      });
    },
    [commentDraft, applyOptimistic]
  );

  const handleApprove = useCallback(async () => {
    if (!studioId || !summary || busy) return;
    setBusy(true);
    try {
      const res = await approveAudit(studioId);
      setSummary(res);
      playSuccess();
      showToast("Auditoría aprobada — el estudio quedó auditado.", "success");
      if (studioId) loadReviews(studioId).catch(() => {});
    } catch (err) {
      const message = err instanceof Error ? err.message : "";
      showToast(
        message.includes("422") ? "Aún no alcanzaste la muestra objetivo." : "No se pudo aprobar la auditoría.",
        "error"
      );
    } finally {
      setBusy(false);
    }
  }, [studioId, summary, busy, showToast, loadReviews]);

  const handleResample = useCallback(async () => {
    if (!studioId || busy) return;
    setBusy(true);
    try {
      const session = await createAuditSession(studioId, true);
      setSummary(session);
      const list = await loadReviews(studioId);
      setSelectedReviewId(list[0]?.id ?? null);
      showToast("Muestra regenerada con el último procesamiento.", "success");
    } catch {
      showToast("No se pudo re-muestrear.", "error");
    } finally {
      setBusy(false);
    }
  }, [studioId, busy, loadReviews, showToast]);

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
        key: "c",
        action: () => focusedItem && !approved && markCorrect(focusedItem),
        description: "Marcar correcto",
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
  }, [items.length, focusedItem, approved, markCorrect, noun]);

  useKeyboardShortcuts("audit-view");

  const selectedReview = useMemo(
    () => reviews.find((r) => r.id === selectedReviewId) ?? null,
    [reviews, selectedReviewId]
  );

  if (!studioId) return null;

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

  if (blockedReason) {
    return (
      <div className="max-w-3xl mx-auto py-4 space-y-4">
        <Breadcrumb
          items={[
            { label: "Proyectos", to: "/" },
            { label: "Estudio", to: `/studios/${studioId}` },
            { label: "Auditoría" },
          ]}
        />
        <div className="card p-8 text-center space-y-3">
          <AlertTriangle className="w-8 h-8 text-p-warning mx-auto" />
          <h1 className="font-heading text-xl font-semibold text-p-text">Auditoría no disponible</h1>
          <p className="text-sm text-p-text-muted">{blockedReason}</p>
          <Link to={`/studios/${studioId}/resolution`} className="btn-primary inline-flex justify-center">
            Ir al Centro de Resolución
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
      <Breadcrumb
        items={[
          { label: "Proyectos", to: "/" },
          { label: studio?.name ?? "Estudio", to: `/studios/${studioId}` },
          { label: "Auditoría" },
        ]}
      />

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
          {!approved && (
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
              <span className="flex gap-2.5 font-mono text-[10px] text-p-text-faint">
                <span className="flex items-center gap-1"><kbd className="kbd-hint">↑↓</kbd>Navegar</span>
                <span className="flex items-center gap-1"><kbd className="kbd-hint">C</kbd>Correcto</span>
                <span className="flex items-center gap-1"><kbd className="kbd-hint">R</kbd>Reasignar</span>
                <span className="flex items-center gap-1"><kbd className="kbd-hint">E</kbd>Comentar</span>
                <span className="flex items-center gap-1"><kbd className="kbd-hint">X</kbd>Eliminar</span>
              </span>
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
                      <th className="px-4 py-2 font-semibold">Respuesta</th>
                      <th className="px-4 py-2 font-semibold">Normalizado</th>
                      <th className="px-4 py-2 font-semibold">Código actual</th>
                      <th className="px-4 py-2 font-semibold">Qué se hizo</th>
                      <th className="px-4 py-2 font-semibold">Comentario</th>
                      <th className="px-4 py-2 font-semibold text-right">Acciones</th>
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
                        onCorrect={() => markCorrect(item)}
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
                          setCommentDraft(item.comment ?? "");
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
  codes: StudioCode[];
  noun: string;
  reassignOpen: boolean;
  reassignCodeId: string;
  newCodeLabel: string;
  commentOpen: boolean;
  commentDraft: string;
  commentInputRef: React.RefObject<HTMLInputElement | null>;
  confirmDelete: boolean;
  onFocus: () => void;
  onCorrect: () => void;
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
  onCorrect,
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
                  className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-p-border text-xs text-p-text"
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
          <span className="line-clamp-2">{item.comment ?? "—"}</span>
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
                onClick={(e) => { e.stopPropagation(); onCorrect(); }}
                disabled={item.status === "correct"}
                className="p-1.5 rounded-lg text-p-success hover:bg-p-success/10 disabled:opacity-30"
                title="Marcar correcto (C)"
                aria-label="Marcar correcto"
              >
                <Check className="w-4 h-4" />
              </button>
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
                  className="px-2.5 py-1 rounded-lg border border-blue-200 bg-blue-50 text-xs font-bold text-blue-700 disabled:opacity-50"
                >
                  Aplicar
                </button>
                <button onClick={onToggleReassign} className="text-xs text-p-text-faint underline underline-offset-2">
                  Cancelar
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Comentario</span>
                <input
                  ref={commentInputRef}
                  type="text"
                  value={commentDraft}
                  onChange={(e) => onCommentChange(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && onSubmitComment()}
                  placeholder="Nota para la constancia de auditoría…"
                  className="input text-xs py-1 flex-1 max-w-md"
                  aria-label="Comentario del item"
                />
                <button
                  onClick={onSubmitComment}
                  className="px-2.5 py-1 rounded-lg border border-blue-200 bg-blue-50 text-xs font-bold text-blue-700"
                >
                  Guardar
                </button>
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
