import { useCallback } from "react";
import { useDropzone } from "react-dropzone";
import {
  FileSpreadsheet,
  UploadCloud,
  X,
  AlertCircle,
  ArrowRight,
  BookOpen,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useWizardStore, type FileEntry } from "@/store/useWizardStore";
import { useWizardOrchestrator } from "@/hooks/useWizardOrchestrator";

async function parseColumns(file: File): Promise<string[]> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const XLSX = await import("xlsx");
        const wb = XLSX.read(new Uint8Array(reader.result as ArrayBuffer), {
          type: "array",
        });
        const ws = wb.Sheets[wb.SheetNames[0]!];
        if (!ws) { resolve([]); return; }
        const rows = XLSX.utils.sheet_to_json<Record<string, string>>(ws, {
          defval: "",
        });
        resolve(Object.keys(rows[0] ?? {}));
      } catch {
        reject(new Error("No se pudo leer el archivo."));
      }
    };
    reader.readAsArrayBuffer(file);
  });
}

export default function UploadStage() {
  const files      = useWizardStore((s) => s.files);
  const setFiles   = useWizardStore((s) => s.setFiles);
  const updateFile = useWizardStore((s) => s.updateFile);
  const { startProcessing } = useWizardOrchestrator();

  const onDrop = useCallback(async (accepted: File[]) => {
    const current = useWizardStore.getState().files;
    const existingNames = new Set(current.map((f) => f.file.name));
    const newFiles = accepted.filter((f) => !existingNames.has(f.name));
    if (newFiles.length === 0) return;

    const entries: FileEntry[] = newFiles.map((f) => ({
      id: crypto.randomUUID(),
      file: f,
      name: f.name.replace(/\.[^.]+$/, ""),
      column: null,
      columns: [],
      roundId: null,
      uploadResult: null,
      items: [],
      metrics: null,
      status: "pending" as const,
    }));

    setFiles([...current, ...entries]);

    entries.forEach(async (entry) => {
      try {
        const columns = await parseColumns(entry.file);
        updateFile(entry.id, {
          columns,
          // Pre-select when there's only one candidate — one less click
          column: columns.length === 1 ? columns[0]! : null,
        });
      } catch {
        updateFile(entry.id, {
          status: "error",
          errorMessage: "No se pudo leer el archivo.",
        });
      }
    });
  }, [setFiles, updateFile]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: true,
    accept: {
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"],
      "text/csv": [".csv"],
    },
  });

  const removeFile = (id: string) => {
    setFiles(useWizardStore.getState().files.filter((f) => f.id !== id));
  };

  const canProcesar =
    files.length > 0 &&
    files.every((f) => f.name.trim() !== "") &&
    files.every((f) => f.columns.length > 0) &&
    files.every((f) => f.column !== null) &&
    files.every((f) => f.status !== "error");

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold text-p-text tracking-tight">
          Carga tus encuestas
        </h1>
        <p className="text-sm text-p-text-muted">
          Sube uno o varios archivos — cada uno se clasifica como una ronda independiente
        </p>
      </div>

      {/* Dropzone */}
      <div
        {...getRootProps()}
        className={[
          "card p-10 text-center cursor-pointer transition-all duration-200",
          isDragActive
            ? "border-2 border-p-accent bg-p-accent/5 scale-[1.01]"
            : "hover:bg-p-bg-subtle",
        ].join(" ")}
      >
        <input {...getInputProps()} />
        <div className="flex flex-col items-center gap-3">
          <div className="w-14 h-14 rounded-full bg-p-accent/10 flex items-center justify-center">
            <UploadCloud className="w-7 h-7 text-p-accent" />
          </div>
          <div>
            <p className="font-medium text-p-text text-sm">
              {isDragActive
                ? "Suelta los archivos aquí"
                : "Arrastra uno o más archivos aquí"}
            </p>
            <p className="text-xs text-p-text-muted mt-0.5">
              o haz clic · .xlsx · .xls · .csv
            </p>
          </div>
        </div>
      </div>

      {/* File list + name + column selection, one continuous surface */}
      <AnimatePresence>
        {files.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-3"
          >
            {/* Compact pipeline note — replaces the old confirm-step modal */}
            <div className="card-subtle px-4 py-3 flex items-start gap-2.5">
              <BookOpen className="w-3.5 h-3.5 text-p-accent shrink-0 mt-0.5" />
              <p className="text-xs text-p-text-muted leading-relaxed">
                Cada archivo se clasifica y revisa por separado — las marcas
                que apruebes mejoran las clasificaciones del siguiente.
              </p>
            </div>

            {files.map((entry) => (
              <motion.div
                key={entry.id}
                layout
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 8, scale: 0.97 }}
                className="card p-4 space-y-3"
              >
                {/* File info row */}
                <div className="flex items-center gap-3">
                  <FileSpreadsheet className="w-8 h-8 text-p-accent shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-p-text-muted truncate">
                      {entry.file.name}
                    </p>
                    <p className="text-[10px] text-p-text-faint">
                      {(entry.file.size / 1024).toFixed(1)} KB
                    </p>
                  </div>

                  {/* Column count badge or loading */}
                  {entry.columns.length > 0 && (
                    <span className="text-[10px] text-p-text-faint bg-p-bg-subtle px-2 py-0.5 rounded-full shrink-0">
                      {entry.columns.length} columnas
                    </span>
                  )}
                  {entry.columns.length === 0 && entry.status !== "error" && (
                    <span className="text-[10px] text-p-accent animate-pulse shrink-0">
                      Leyendo...
                    </span>
                  )}
                  {entry.status === "error" && (
                    <AlertCircle className="w-4 h-4 text-p-error shrink-0" />
                  )}

                  <button
                    onClick={() => removeFile(entry.id)}
                    className="text-p-text-faint hover:text-p-error transition-colors shrink-0"
                    aria-label="Eliminar archivo"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>

                {entry.status === "error" ? (
                  <p className="text-xs text-p-error">{entry.errorMessage}</p>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
                        Nombre de la ronda
                      </label>
                      <input
                        type="text"
                        value={entry.name}
                        onChange={(e) =>
                          updateFile(entry.id, { name: e.target.value })
                        }
                        placeholder='ej. "Q3 2024 Latam"'
                        className="input w-full text-sm"
                      />
                    </div>

                    <div className="space-y-1.5">
                      <label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
                        Columna de respuestas
                      </label>
                      <select
                        value={entry.column ?? ""}
                        disabled={entry.columns.length === 0}
                        onChange={(e) =>
                          updateFile(entry.id, { column: e.target.value || null })
                        }
                        className="input w-full text-sm disabled:opacity-50"
                      >
                        <option value="">Selecciona...</option>
                        {entry.columns.map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                )}
              </motion.div>
            ))}

            <button
              onClick={() => startProcessing()}
              disabled={!canProcesar}
              className="btn-primary w-full justify-center"
            >
              Procesar {files.length}{" "}
              {files.length === 1 ? "archivo" : "archivos"}
              <ArrowRight className="w-4 h-4" />
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
