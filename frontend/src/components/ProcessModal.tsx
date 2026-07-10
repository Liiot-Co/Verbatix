import { createPortal } from "react-dom";
import { motion } from "framer-motion";
import { X, Check, BookOpen } from "lucide-react";
import { useWizardStore } from "@/store/useWizardStore";

interface Props {
  onClose: () => void;
  onConfirm: () => void;
}

export default function ProcessModal({ onClose, onConfirm }: Props) {
  const files      = useWizardStore((s) => s.files);
  const updateFile = useWizardStore((s) => s.updateFile);

  const allColumnsSelected = files.every((f) => f.column !== null);

  return createPortal(
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-40 flex items-center justify-center p-4"
      style={{
        background: "rgba(44,38,34,0.45)",
        backdropFilter: "blur(6px)",
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <motion.div
        initial={{ scale: 0.97, y: 10 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.97, y: 10 }}
        transition={{ duration: 0.16, ease: "easeOut" }}
        className="card w-full max-w-lg p-6 space-y-5 max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-p-text">
            Configurar clasificación
          </h2>
          <button
            onClick={onClose}
            className="text-p-text-faint hover:text-p-text transition-colors"
            aria-label="Cerrar"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Pipeline explanation */}
        <div className="card-subtle px-4 py-3 space-y-2">
          <div className="flex items-center gap-2 mb-1">
            <BookOpen className="w-3.5 h-3.5 text-p-accent" />
            <p className="text-xs font-semibold text-p-text uppercase tracking-wide">
              Cómo funciona
            </p>
          </div>
          <p className="text-sm text-p-text-muted leading-relaxed">
            La clasificación se ejecuta por archivo. Cada archivo se revisa
            individualmente antes de procesar el siguiente.
          </p>
          <p className="text-sm text-p-text-muted leading-relaxed">
            Las marcas aprendidas en revisiones anteriores mejoran las
            clasificaciones siguientes — el sistema aprende con cada ronda.
          </p>
        </div>

        {/* Per-file column selectors */}
        <div className="space-y-4">
          <p className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
            Columna de respuestas abiertas
          </p>
          {files.map((entry) => (
            <div key={entry.id} className="space-y-1.5">
              <label className="text-sm font-medium text-p-text block truncate">
                {entry.name}
                <span className="ml-1.5 text-p-text-faint text-xs font-normal">
                  ({entry.file.name})
                </span>
              </label>
              <select
                value={entry.column ?? ""}
                onChange={(e) =>
                  updateFile(entry.id, {
                    column: e.target.value || null,
                  })
                }
                className="input w-full text-sm"
              >
                <option value="">Selecciona una columna...</option>
                {entry.columns.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 pt-1">
          <button onClick={onClose} className="btn-ghost text-sm">
            Cancelar
          </button>
          <button
            onClick={onConfirm}
            disabled={!allColumnsSelected}
            className="btn-primary text-sm"
          >
            <Check className="w-4 h-4" /> Confirmar y Clasificar
          </button>
        </div>
      </motion.div>
    </motion.div>,
    document.body
  );
}
