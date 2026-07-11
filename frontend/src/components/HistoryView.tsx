import { useEffect, useState } from "react";
import { ChevronRight, Trash2, Import } from "lucide-react";
import { useWizardStore } from "@/store/useWizardStore";
import { useWizardOrchestrator } from "@/hooks/useWizardOrchestrator";
import { getStudies, getRounds, deleteRound, importCodebook, createStudy } from "@/api/client";
import type { MarketStudy, Round } from "@/api/types";

export default function HistoryView() {
  const showToast = useWizardStore((s) => s.showToast);
  const { continueRound } = useWizardOrchestrator();

  const [studies, setStudies] = useState<MarketStudy[]>([]);
  const [rounds, setRounds] = useState<Round[]>([]);
  const [importingIntoStudyId, setImportingIntoStudyId] = useState<number | null>(null);
  const [newStudyName, setNewStudyName] = useState("");

  const reload = () => {
    getStudies().then(setStudies).catch(() => {});
    getRounds().then(setRounds).catch(() => {});
  };

  useEffect(reload, []);

  const roundsByStudy = (studyId: number) => rounds.filter((r) => r.study_id === studyId);
  const orphanRounds = rounds.filter((r) => !r.study_id);

  const handleDelete = async (round: Round) => {
    if (!confirm(`¿Eliminar el round "${round.name}"? Esta acción no se puede deshacer.`)) return;
    try {
      await deleteRound(round.id);
      showToast(`Round "${round.name}" eliminado`, "success");
      reload();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Error desconocido";
      showToast(`No se pudo eliminar: ${msg}`, "error");
    }
  };

  const handleImport = async (destStudyId: number, sourceStudyId: number) => {
    try {
      const res = await importCodebook(destStudyId, sourceStudyId);
      showToast(`Importados ${res.imported_nets} netos, ${res.imported_codes} códigos`, "success");
      setImportingIntoStudyId(null);
      reload();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Error desconocido";
      showToast(`No se pudo importar: ${msg}`, "error");
    }
  };

  const handleCreateStudy = async () => {
    if (!newStudyName.trim()) return;
    await createStudy(newStudyName.trim());
    setNewStudyName("");
    reload();
  };

  const renderRound = (round: Round) => {
    const pending = round.requires_human ?? 0;
    const total = round.total ?? 0;
    const complete = total > 0 && pending === 0;
    return (
      <div
        key={round.id}
        className="flex items-center gap-3 px-4 py-3 rounded-lg border border-p-border bg-p-surface"
      >
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-p-text truncate">{round.name}</div>
          <div className="text-[11px] font-subtitle text-p-text-faint">
            {total} registros · {pending} pendientes
          </div>
        </div>
        {complete ? (
          <span className="text-[11px] font-subtitle uppercase tracking-wider px-2 py-0.5 rounded-full text-p-success bg-p-success/10 border border-p-success/20">
            Completado
          </span>
        ) : (
          <span className="text-[11px] font-subtitle uppercase tracking-wider px-2 py-0.5 rounded-full text-p-warning bg-p-warning/10 border border-p-warning/20">
            En proceso
          </span>
        )}
        <button
          className="text-xs font-medium text-p-accent hover:underline flex items-center gap-1"
          onClick={() => continueRound(round)}
        >
          {complete ? "Ver dashboard" : "Continuar revisión"}
          <ChevronRight className="w-3.5 h-3.5" />
        </button>
        <button
          className="text-p-text-faint hover:text-p-error transition-colors"
          onClick={() => handleDelete(round)}
          aria-label="Eliminar round"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>
    );
  };

  return (
    <div className="flex-1 overflow-y-auto px-8 py-7">
      <div className="mb-6 flex items-end justify-between">
        <div>
          <div className="font-subtitle text-[11px] tracking-[0.18em] uppercase text-p-text-faint mb-1.5">
            Actividad · Timeline
          </div>
          <h2 className="font-heading font-extrabold text-2xl tracking-tight text-p-text">
            Historial de estudios
          </h2>
        </div>
        <div className="flex gap-2">
          <input
            className="input text-sm w-48"
            placeholder="Nuevo estudio..."
            value={newStudyName}
            onChange={(e) => setNewStudyName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreateStudy()}
          />
          <button className="btn-primary text-xs px-3" onClick={handleCreateStudy}>
            Crear
          </button>
        </div>
      </div>

      <div className="flex flex-col gap-6">
        {studies.map((study) => (
          <div key={study.id} className="card p-4">
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="font-semibold text-sm text-p-text">{study.name}</div>
                <div className="text-[11px] font-subtitle text-p-text-faint">
                  {study.codebook_size} códigos en el libro
                </div>
              </div>
              {importingIntoStudyId === study.id ? (
                <div className="flex items-center gap-2">
                  <select
                    className="input text-xs py-1 w-40"
                    onChange={(e) => handleImport(study.id, Number(e.target.value))}
                    defaultValue=""
                  >
                    <option value="" disabled>Importar de...</option>
                    {studies.filter((s) => s.id !== study.id).map((s) => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                  </select>
                  <button className="btn-ghost text-xs py-1 px-2" onClick={() => setImportingIntoStudyId(null)}>
                    Cancelar
                  </button>
                </div>
              ) : (
                <button
                  className="btn-ghost text-xs flex items-center gap-1.5"
                  onClick={() => setImportingIntoStudyId(study.id)}
                >
                  <Import className="w-3.5 h-3.5" />
                  Importar libro de códigos
                </button>
              )}
            </div>
            <div className="flex flex-col gap-2">
              {roundsByStudy(study.id).length === 0 ? (
                <div className="text-xs text-p-text-faint">Sin rounds todavía.</div>
              ) : (
                roundsByStudy(study.id).map(renderRound)
              )}
            </div>
          </div>
        ))}

        {orphanRounds.length > 0 && (
          <div className="card p-4">
            <div className="font-semibold text-sm text-p-text mb-3">Sin estudio asignado</div>
            <div className="flex flex-col gap-2">{orphanRounds.map(renderRound)}</div>
          </div>
        )}
      </div>
    </div>
  );
}
