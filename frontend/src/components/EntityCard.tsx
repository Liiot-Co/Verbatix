import { useEffect, useRef, useState } from "react";
import { Check, X, Pencil, ChevronRight } from "lucide-react";
import type { SurveyItem } from "@/api/types";

interface Props {
  item: SurveyItem;
  focused: boolean;
  onFocus: () => void;
  onApprove: () => void;
  onReject: () => void;
  onEdit: (brand: string) => void;
  /** Context-only card (codebook mode) — no actions, no keyboard shortcuts. */
  readOnly?: boolean;
}

export default function EntityCard({ item, focused, onFocus, onApprove, onReject, onEdit, readOnly }: Props) {
  const [editing, setEditing] = useState(false);
  const [editVal, setEditVal] = useState(item.suggested_brand ?? "");
  const cardRef   = useRef<HTMLDivElement>(null);
  const inputRef  = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (focused) cardRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [focused]);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  // Game-like bindings: ← reject, → / Enter approve (swipe feel), e edit.
  // a/r kept for muscle memory from before the swipe metaphor.
  useEffect(() => {
    if (!focused || readOnly) return;
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT") return;
      if (e.key === "a" || e.key === "ArrowRight" || e.key === "Enter") { e.preventDefault(); onApprove(); }
      else if (e.key === "r" || e.key === "ArrowLeft")                  { e.preventDefault(); onReject(); }
      else if (e.key === "e")                                          { e.preventDefault(); setEditing(true); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [focused, readOnly, onApprove, onReject]);

  const confirmEdit = () => {
    const v = editVal.trim();
    if (!v) return;
    onEdit(v);
    setEditing(false);
  };

  return (
    <div
      ref={cardRef}
      onClick={onFocus}
      onFocus={onFocus}
      tabIndex={0}
      className={[
        "card p-5 space-y-4 outline-none transition-shadow",
        focused && !readOnly ? "ring-2 ring-p-accent/50" : "",
      ].join(" ")}
    >
      {/* Original text */}
      <p className="text-xs text-p-text-muted font-subtitle leading-relaxed line-clamp-2">
        {item.original_text}
      </p>

      {/* extracted → suggested */}
      <div className="flex items-center gap-2 flex-wrap">
        {item.extracted_term && (
          <>
            <span className="text-sm text-p-text-muted">{item.extracted_term}</span>
            <ChevronRight className="w-3.5 h-3.5 text-p-text-faint shrink-0" />
          </>
        )}
        <span className="text-sm font-semibold text-p-accent">
          {item.suggested_brand ?? "Sin sugerencia"}
        </span>
      </div>

      {/* Confidence */}
      <div className="space-y-1">
        <div className="flex justify-between text-xs text-p-text-faint">
          <span>confianza</span>
          <span className="font-subtitle">{Math.round(item.confidence * 100)}%</span>
        </div>
        <div className="confidence-bar">
          <div className="confidence-fill" style={{ "--conf": item.confidence } as React.CSSProperties} />
        </div>
      </div>

      {/* Actions — hidden entirely in readOnly (codebook mode gives this card no keyboard binding to conflict with) */}
      {!readOnly && (
        <div className="flex items-center gap-2 flex-wrap">
          {editing ? (
            <div className="flex items-center gap-2 flex-1">
              <input
                ref={inputRef}
                value={editVal}
                onChange={(e) => setEditVal(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter")  confirmEdit();
                  if (e.key === "Escape") setEditing(false);
                }}
                placeholder="Nombre de marca..."
                className="input flex-1 text-xs py-1.5"
              />
              <button onClick={confirmEdit} className="btn-primary py-1.5 px-3 text-xs">OK</button>
              <button onClick={() => setEditing(false)} className="btn-ghost py-1.5 px-3 text-xs">✕</button>
            </div>
          ) : (
            <>
              {/* Primary CTA — the suggested brand is usually correct */}
              <button
                onClick={(e) => { e.stopPropagation(); onApprove(); }}
                className="btn-primary text-xs"
                title="Aprobar (→ / Enter)"
              >
                <Check className="w-3.5 h-3.5" /> Aprobar
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); setEditing(true); }}
                className="btn-ghost text-xs"
                title="Editar (E)"
              >
                <Pencil className="w-3.5 h-3.5" /> Editar
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); onReject(); }}
                className="btn-danger text-xs"
                title="Rechazar (←)"
              >
                <X className="w-3.5 h-3.5" /> Rechazar
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
