import { useCallback, useEffect, useState } from "react";
import { useDropzone } from "react-dropzone";
import { FileSpreadsheet, UploadCloud, ArrowRight, AlertCircle, Plus, ChevronDown } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useAppStore } from "@/store/useAppStore";
import { getRounds, createRound, uploadFile } from "@/api/client";
import Loader from "@/components/Loader";
import type { Round } from "@/api/types";

/* ── Round Selector ── */
function RoundSelector({
  rounds,
  selected,
  onSelect,
  onCreate,
}: {
  rounds: Round[];
  selected: Round | null;
  onSelect: (r: Round) => void;
  onCreate: (name: string) => void;
}) {
  const [open, setOpen]       = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName]  = useState("");

  const handleCreate = () => {
    const name = newName.trim();
    if (!name) return;
    onCreate(name);
    setNewName("");
    setCreating(false);
    setOpen(false);
  };

  return (
    <div className="space-y-1.5">
      <label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
        Ronda de encuesta
      </label>

      {/* Trigger */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="input flex items-center justify-between text-left"
      >
        <span className={selected ? "text-p-text" : "text-p-text-faint"}>
          {selected ? selected.name : "Selecciona o crea una ronda..."}
        </span>
        <ChevronDown className={`w-4 h-4 text-p-text-faint transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4, scaleY: 0.95 }}
            animate={{ opacity: 1, y: 0, scaleY: 1 }}
            exit={{ opacity: 0, y: -4, scaleY: 0.95 }}
            style={{ originY: "top" }}
            className="card p-1 space-y-0.5 shadow-lg"
          >
            {/* Existing rounds */}
            {rounds.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => { onSelect(r); setOpen(false); }}
                className={[
                  "w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-colors text-left",
                  selected?.id === r.id
                    ? "bg-p-accent/10 text-p-accent font-medium"
                    : "hover:bg-p-bg-subtle text-p-text",
                ].join(" ")}
              >
                <span>{r.name}</span>
                {r.requires_human !== undefined && (
                  <span className="text-[10px] text-p-text-faint font-mono">
                    {r.requires_human} pendientes
                  </span>
                )}
              </button>
            ))}

            <div className="border-t border-p-border my-1" />

            {/* Create new */}
            {creating ? (
              <div className="px-2 py-1 flex gap-2">
                <input
                  autoFocus
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") handleCreate(); if (e.key === "Escape") setCreating(false); }}
                  placeholder='ej. "Q3 2024 Latam"'
                  className="input flex-1 text-xs py-1.5"
                />
                <button onClick={handleCreate} className="btn-primary py-1.5 px-3 text-xs">
                  Crear
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setCreating(true)}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-p-accent hover:bg-p-accent/5 transition-colors"
              >
                <Plus className="w-3.5 h-3.5" /> Nueva ronda
              </button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ── Step1Upload ── */
export default function Step1Upload() {
  const setUploadResult = useAppStore((s) => s.setUploadResult);
  const setStep         = useAppStore((s) => s.setStep);
  const showToast       = useAppStore((s) => s.showToast);
  const loading         = useAppStore((s) => s.loading);
  const setLoading      = useAppStore((s) => s.setLoading);
  const rounds          = useAppStore((s) => s.rounds);
  const setRounds       = useAppStore((s) => s.setRounds);
  const activeRound     = useAppStore((s) => s.activeRound);
  const setActiveRound  = useAppStore((s) => s.setActiveRound);

  const [file, setFile]         = useState<File | null>(null);
  const [columns, setColumns]   = useState<string[]>([]);
  const [preview, setPreview]   = useState<Record<string, string>[]>([]);
  const [column, setColumn]     = useState("");
  const [parseErr, setParseErr] = useState("");

  /* Load rounds on mount */
  useEffect(() => {
    getRounds()
      .then(setRounds)
      .catch(() => {/* backend may not support rounds yet */});
  }, [setRounds]);

  const handleCreateRound = async (name: string) => {
    try {
      const r = await createRound(name);
      setRounds([...rounds, r]);
      setActiveRound(r);
      showToast(`Ronda "${name}" creada`, "success");
    } catch {
      showToast("No se pudo crear la ronda", "error");
    }
  };

  const onDrop = useCallback(async (accepted: File[]) => {
    const f = accepted[0];
    if (!f) return;
    setFile(f);
    setParseErr("");
    setColumn("");

    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const XLSX = await import("xlsx");
        const wb = XLSX.read(new Uint8Array(reader.result as ArrayBuffer), { type: "array" });
        const ws = wb.Sheets[wb.SheetNames[0]!];
        if (!ws) return;
        const rows = XLSX.utils.sheet_to_json<Record<string, string>>(ws, { defval: "" });
        const cols = Object.keys(rows[0] ?? {});
        setColumns(cols);
        setPreview(rows.slice(0, 4));
      } catch {
        setParseErr("No se pudo leer el archivo.");
      }
    };
    reader.readAsArrayBuffer(f);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"],
      "text/csv": [".csv"],
    },
    maxFiles: 1,
  });

  const handleSubmit = async () => {
    if (!file || !column) return;
    if (!activeRound) { showToast("Selecciona una ronda primero", "error"); return; }
    setLoading(true);
    try {
      const result = await uploadFile(file, column, activeRound.id);
      setUploadResult(result);
      showToast(
        `${result.total} respuestas · ${result.auto_approved} auto · ${result.requires_human} para revisar`,
        "success",
      );
      setStep(2);
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Error al procesar", "error");
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <Loader text="Clasificando respuestas..." />;

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold text-p-text tracking-tight">Sube tu encuesta</h1>
        <p className="text-sm text-p-text-muted">Paso 1 — Selecciona la ronda y carga el archivo</p>
      </div>

      {/* Round selector */}
      <div className="card p-5">
        <RoundSelector
          rounds={rounds}
          selected={activeRound}
          onSelect={setActiveRound}
          onCreate={handleCreateRound}
        />
      </div>

      {/* Dropzone */}
      <div
        {...getRootProps()}
        className={[
          "card p-10 text-center cursor-pointer transition-all duration-200",
          isDragActive
            ? "border-2 border-p-accent bg-p-accent/5 scale-[1.01]"
            : "hover:border-p-border-mid hover:bg-p-surface-2/60",
        ].join(" ")}
      >
        <input {...getInputProps()} />
        <AnimatePresence mode="wait">
          {file ? (
            <motion.div key="file" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
              className="flex flex-col items-center gap-2">
              <FileSpreadsheet className="w-10 h-10 text-p-accent" />
              <p className="font-medium text-p-text text-sm">{file.name}</p>
              <p className="text-xs text-p-text-muted">{(file.size / 1024).toFixed(1)} KB</p>
            </motion.div>
          ) : (
            <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
              className="flex flex-col items-center gap-3">
              <div className="w-14 h-14 rounded-full bg-p-accent/10 flex items-center justify-center">
                <UploadCloud className="w-7 h-7 text-p-accent" />
              </div>
              <div>
                <p className="font-medium text-p-text text-sm">
                  {isDragActive ? "Suelta aquí" : "Arrastra tu archivo aquí"}
                </p>
                <p className="text-xs text-p-text-muted mt-0.5">o haz clic · .xlsx · .xls · .csv</p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {parseErr && (
        <div className="flex items-center gap-2 text-sm text-p-error card-subtle px-4 py-3">
          <AlertCircle className="w-4 h-4 shrink-0" /> {parseErr}
        </div>
      )}

      <AnimatePresence>
        {columns.length > 0 && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="card p-5 space-y-4">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
                Columna de respuesta abierta
              </label>
              <select value={column} onChange={(e) => setColumn(e.target.value)} className="input">
                <option value="">Selecciona una columna...</option>
                {columns.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>

            {preview.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-p-border">
                      {columns.slice(0, 4).map((c) => (
                        <th key={c} className={`text-left py-1.5 pr-3 font-medium ${c === column ? "text-p-accent" : "text-p-text-muted"}`}>
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.map((row, i) => (
                      <tr key={i} className="border-b border-p-border/50">
                        {columns.slice(0, 4).map((c) => (
                          <td key={c} className={`py-1.5 pr-3 truncate max-w-[180px] ${c === column ? "text-p-text font-medium" : "text-p-text-muted"}`}>
                            {row[c]}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <button onClick={handleSubmit} disabled={!column || !activeRound} className="btn-primary w-full justify-center">
              Clasificar respuestas <ArrowRight className="w-4 h-4" />
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
