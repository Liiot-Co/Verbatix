import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Check, X, Pencil, ChevronRight } from "lucide-react";
import type { SurveyItem } from "@/api/types";

interface Props {
  item: SurveyItem;
  focused: boolean;
  onFocus: () => void;
  onApprove: () => void;
  onReject: () => void;
  onEdit: (brand: string) => void;
}

export default function EntityCard({ item, focused, onFocus, onApprove, onReject, onEdit }: Props) {
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

  useEffect(() => {
    if (!focused) return;
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT") return;
      if (e.key === "Enter" || e.key === "a") { e.preventDefault(); onApprove(); }
      else if (e.key === "r")                  { e.preventDefault(); onReject(); }
      else if (e.key === "e")                  { e.preventDefault(); setEditing(true); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [focused, onApprove, onReject]);

  const confirmEdit = () => {
    const v = editVal.trim();
    if (!v) return;
    onEdit(v);
    setEditing(false);
  };

  return (
    <motion.div
      ref={cardRef}
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: 40, scale: 0.96 }}
      transition={{ layout: { duration: 0.2 } }}
      onClick={onFocus}
      onFocus={onFocus}
      tabIndex={0}
      className={[
        "card p-4 space-y-3 cursor-pointer outline-none transition-all",
        focused ? "ring-2 ring-p-accent shadow-md" : "hover:border-p-border-mid",
      ].join(" ")}
    >
      {/* Original text */}
      <p className="text-xs text-p-text-muted font-mono leading-relaxed line-clamp-2">
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
        <div className="flex justify-between text-[10px] text-p-text-faint">
          <span>confianza</span>
          <span className="font-mono">{Math.round(item.confidence * 100)}%</span>
        </div>
        <div className="confidence-bar">
          <div className="confidence-fill" style={{ "--conf": item.confidence } as React.CSSProperties} />
        </div>
      </div>

      {/* Actions */}
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
            <button
              onClick={(e) => { e.stopPropagation(); onApprove(); }}
              className="btn-ghost text-xs text-p-success border-emerald-200 hover:bg-emerald-50"
              title="Aprobar (Enter / A)"
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
              title="Rechazar (R)"
            >
              <X className="w-3.5 h-3.5" /> Rechazar
            </button>
            {focused && (
              <span className="ml-auto text-[10px] text-p-text-faint hidden sm:inline">
                ↑↓ navegar · Enter aprobar · E editar · R rechazar
              </span>
            )}
          </>
        )}
      </div>
    </motion.div>
  );
}
