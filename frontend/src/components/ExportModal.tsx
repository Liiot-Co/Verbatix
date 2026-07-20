import { useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { motion } from "framer-motion";

interface ExportModalProps {
  exporting: boolean;
  onCancel: () => void;
  onConfirm: (formats: string[]) => void;
}

const OPTIONS: { value: string; label: string; hint: string }[] = [
  { value: "excel", label: "Excel", hint: "Libro de Códigos (.xlsx)" },
  { value: "sql", label: "SQL", hint: "Metadatos + datos (.txt)" },
  { value: "onenextcase", label: "OnNextCase", hint: "Formato de casos (.txt)" },
  { value: "mdd", label: "MDD", hint: "Metadata Dimensions (.mdd)" },
];

/** Modal de selección de formatos para el ZIP de exportación (REQ-13). */
export function ExportModal({ exporting, onCancel, onConfirm }: ExportModalProps) {
  const [selected, setSelected] = useState<string[]>(["excel", "sql", "onenextcase"]);

  const toggle = (value: string) =>
    setSelected((current) =>
      current.includes(value) ? current.filter((v) => v !== value) : [...current, value],
    );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-p-text/20 backdrop-blur-[2px]"
      onMouseDown={() => !exporting && onCancel()}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.96, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        className="w-full max-w-md glow-card glow-card-3 p-5 sm:p-6 space-y-4"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="space-y-1">
          <h2 className="font-heading text-lg font-semibold text-p-text tracking-tight">
            Exportar paquete
          </h2>
          <p className="text-sm text-p-text-muted">Selecciona los archivos a incluir en el ZIP.</p>
        </div>

        <div className="space-y-2">
          {OPTIONS.map((opt) => (
            <label
              key={opt.value}
              className={`card-subtle p-3 flex items-start gap-2 text-sm cursor-pointer ${
                selected.includes(opt.value) ? "border-p-accent bg-p-accent/5" : ""
              }`}
            >
              <input
                type="checkbox"
                className="mt-0.5"
                checked={selected.includes(opt.value)}
                onChange={() => toggle(opt.value)}
              />
              <span>
                <span className="block font-medium text-p-text">{opt.label}</span>
                <span className="block text-xs text-p-text-muted">{opt.hint}</span>
              </span>
            </label>
          ))}
        </div>

        <div className="flex flex-col sm:flex-row gap-2 sm:justify-end">
          <button
            type="button"
            className="btn-ghost text-sm py-2 order-2 sm:order-1"
            onClick={onCancel}
            disabled={exporting}
          >
            Cancelar
          </button>
          <button
            type="button"
            className="btn-primary text-sm py-2 order-1 sm:order-2 disabled:opacity-50"
            onClick={() => onConfirm(selected)}
            disabled={exporting || selected.length === 0}
          >
            {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
            Descargar ZIP
          </button>
        </div>
      </motion.div>
    </div>
  );
}
