import { useEffect, useState } from "react";
import { LayoutGrid, History as HistoryIcon, Tag, Plus, ChevronDown } from "lucide-react";
import { useWizardStore, type AppView } from "@/store/useWizardStore";
import { getStudies, createStudy } from "@/api/client";
import type { MarketStudy } from "@/api/types";

const NAV_ITEMS: { view: AppView; label: string; icon: typeof LayoutGrid }[] = [
  { view: "project", label: "Proyecto", icon: LayoutGrid },
  { view: "history", label: "Historial", icon: HistoryIcon },
  { view: "codebook", label: "Códigos", icon: Tag },
];

interface AppShellProps {
  children: React.ReactNode;
}

export default function AppShell({ children }: AppShellProps) {
  const view = useWizardStore((s) => s.view);
  const setView = useWizardStore((s) => s.setView);
  const activeStudyId = useWizardStore((s) => s.activeStudyId);
  const setActiveStudyId = useWizardStore((s) => s.setActiveStudyId);

  const [studies, setStudies] = useState<MarketStudy[]>([]);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");

  const loadStudies = () => {
    getStudies()
      .then((list) => {
        setStudies(list);
        if (!activeStudyId && list[0]) setActiveStudyId(list[0].id);
      })
      .catch(() => {});
  };

  useEffect(() => {
    loadStudies();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeStudy = studies.find((s) => s.id === activeStudyId) ?? null;

  const handleCreateStudy = async () => {
    if (!newName.trim()) return;
    const study = await createStudy(newName.trim());
    setNewName("");
    setCreating(false);
    setStudies((prev) => [study, ...prev]);
    setActiveStudyId(study.id);
  };

  return (
    <div className="flex h-screen bg-p-bg overflow-hidden">
      {/* Sidebar */}
      <aside className="w-[220px] shrink-0 h-screen sticky top-0 flex flex-col border-r border-p-border bg-p-surface">
        <div className="p-3.5 border-b border-p-border">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-p-accent to-p-accent-mid flex items-center justify-center shrink-0">
              <svg width="17" height="13" viewBox="0 0 17 13" fill="none">
                <polyline points="1,1.5 4.5,11.5 8.5,3.5 12.5,11.5 16,1.5" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <div>
              <div className="font-sans font-extrabold text-[15px] tracking-tight text-p-text leading-tight">Verbatix</div>
              <div className="font-mono text-[10px] tracking-[0.18em] uppercase text-p-text-faint mt-0.5">Studio</div>
            </div>
          </div>
        </div>

        <nav className="flex-1 p-2 flex flex-col gap-1 overflow-y-auto">
          <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-p-text-faint px-2 pt-2.5 pb-1.5">
            Principal
          </div>
          {NAV_ITEMS.map(({ view: v, label, icon: Icon }) => {
            const active = view === v;
            return (
              <button
                key={v}
                onClick={() => setView(v)}
                className={[
                  "relative flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                  active ? "bg-p-bg-subtle text-p-text" : "text-p-text-muted hover:bg-p-bg-subtle/60 hover:text-p-text",
                ].join(" ")}
              >
                {active && (
                  <span className="absolute left-0 top-1.5 bottom-1.5 w-[2.5px] bg-p-accent rounded-r" />
                )}
                <Icon className="w-3.5 h-3.5 shrink-0" />
                <span className="flex-1 text-left">{label}</span>
              </button>
            );
          })}

          <div className="h-px bg-p-border my-2.5 mx-0.5" />
          <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-p-text-faint px-2 pb-1.5">
            Estudio activo
          </div>

          {activeStudy ? (
            <div className="p-3 rounded-lg border border-p-border bg-p-bg-subtle/60 mx-0.5">
              <div className="font-mono text-[10.5px] tracking-wider uppercase text-p-accent mb-1">
                EST-{String(activeStudy.id).padStart(4, "0")}
              </div>
              <div className="text-sm font-semibold text-p-text leading-tight mb-2">{activeStudy.name}</div>
              <div className="text-[11px] font-mono text-p-text-faint">
                {activeStudy.codebook_size} códigos · {activeStudy.round_count} rondas
              </div>
            </div>
          ) : (
            <div className="mx-0.5 text-xs text-p-text-faint px-2">Sin estudio activo</div>
          )}

          <div className="mx-0.5 mt-1.5">
            {creating ? (
              <div className="flex flex-col gap-1.5">
                <input
                  autoFocus
                  className="input text-xs py-1.5"
                  placeholder="Nombre del estudio"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleCreateStudy();
                    if (e.key === "Escape") setCreating(false);
                  }}
                />
                <div className="flex gap-1.5">
                  <button className="btn-ghost text-xs py-1 px-2 flex-1" onClick={handleCreateStudy}>
                    Crear
                  </button>
                  <button className="btn-ghost text-xs py-1 px-2" onClick={() => setCreating(false)}>
                    Cancelar
                  </button>
                </div>
              </div>
            ) : (
              <button
                className="flex items-center gap-1.5 text-xs text-p-text-muted hover:text-p-text px-2 py-1"
                onClick={() => setCreating(true)}
              >
                <Plus className="w-3 h-3" />
                Nuevo estudio
              </button>
            )}
          </div>

          {studies.length > 1 && (
            <div className="mx-0.5 mt-1">
              <label className="sr-only" htmlFor="study-select">Estudio</label>
              <div className="relative">
                <select
                  id="study-select"
                  className="input text-xs py-1.5 pr-6 appearance-none cursor-pointer"
                  value={activeStudyId ?? ""}
                  onChange={(e) => setActiveStudyId(Number(e.target.value))}
                >
                  {studies.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
                <ChevronDown className="w-3 h-3 absolute right-2 top-1/2 -translate-y-1/2 text-p-text-faint pointer-events-none" />
              </div>
            </div>
          )}
        </nav>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0 bg-p-bg">
        {children}
      </div>
    </div>
  );
}
