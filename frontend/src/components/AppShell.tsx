import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Upload, ScanSearch, LayoutDashboard, History as HistoryIcon, Tag, Plus, ChevronDown } from "lucide-react";
import { useWizardStore } from "@/store/useWizardStore";
import { getStudies, createStudy } from "@/api/client";
import type { MarketStudy } from "@/api/types";

const NAV_ITEMS: { path: string; label: string; icon: typeof Upload }[] = [
  { path: "/project/upload", label: "Carga", icon: Upload },
  { path: "/project/review", label: "Revisión", icon: ScanSearch },
  { path: "/project/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { path: "/history", label: "Historial", icon: HistoryIcon },
  { path: "/codebook", label: "Códigos", icon: Tag },
];

interface AppShellProps {
  children: React.ReactNode;
}

export default function AppShell({ children }: AppShellProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const activeStudyId = useWizardStore((s) => s.activeStudyId);
  const setActiveStudyId = useWizardStore((s) => s.setActiveStudyId);
  const setActiveStudyName = useWizardStore((s) => s.setActiveStudyName);
  const setActiveStudyMode = useWizardStore((s) => s.setActiveStudyMode);

  const [studies, setStudies] = useState<MarketStudy[]>([]);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");

  const loadStudies = () => {
    // No silent auto-select — landing on a study is an explicit choice
    // made from the study picker (see StudyPicker.tsx), not a side effect
    // of the sidebar mounting.
    getStudies()
      .then((list) => setStudies(list))
      .catch(() => {});
  };

  useEffect(() => {
    loadStudies();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeStudy = studies.find((s) => s.id === activeStudyId) ?? null;

  useEffect(() => {
    setActiveStudyName(activeStudy?.name ?? null);
    if (activeStudy?.mode) setActiveStudyMode(activeStudy.mode);
  }, [activeStudy?.name, activeStudy?.mode, setActiveStudyName, setActiveStudyMode]);

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
              <div className="font-heading font-extrabold text-[15px] tracking-tight text-p-text leading-tight">Verbatix</div>
              <div className="font-subtitle text-[10px] tracking-[0.18em] uppercase text-p-text-faint mt-0.5">Studio</div>
            </div>
          </div>
        </div>

        <nav className="flex-1 p-2 flex flex-col gap-1 overflow-y-auto">
          <div className="font-subtitle text-[10px] tracking-[0.22em] uppercase text-p-text-faint px-2 pt-2.5 pb-1.5">
            Principal
          </div>
          {NAV_ITEMS.map(({ path, label, icon: Icon }) => {
            const active = location.pathname === path;
            return (
              <button
                key={path}
                onClick={() => navigate(path)}
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
          <div className="font-subtitle text-[10px] tracking-[0.22em] uppercase text-p-text-faint px-2 pb-1.5">
            Estudio activo
          </div>

          {activeStudy ? (
            <div className="p-3 rounded-lg border border-p-border bg-p-bg-subtle/60 mx-0.5">
              <div className="font-subtitle text-[10.5px] tracking-wider uppercase text-p-accent mb-1">
                EST-{String(activeStudy.id).padStart(4, "0")}
              </div>
              <div className="text-sm font-semibold text-p-text leading-tight mb-2">{activeStudy.name}</div>
              <div className="text-[11px] font-subtitle text-p-text-faint">
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
      <div className="relative flex-1 flex flex-col overflow-hidden min-w-0 bg-p-bg">
        {/* Subtle corner glows — frame the content area, decorative only */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 z-0"
          style={{
            background:
              "radial-gradient(520px circle at 100% 0%, oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h) / 0.07), transparent 55%)," +
              "radial-gradient(520px circle at 0% 100%, oklch(var(--p-accent-mid-l) var(--p-accent-mid-c) var(--p-accent-mid-h) / 0.06), transparent 55%)," +
              "radial-gradient(400px circle at 0% 0%, oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h) / 0.03), transparent 55%)," +
              "radial-gradient(400px circle at 100% 100%, oklch(var(--p-accent-mid-l) var(--p-accent-mid-c) var(--p-accent-mid-h) / 0.03), transparent 55%)",
          }}
        />
        <div className="relative z-10 flex-1 flex flex-col overflow-hidden min-w-0">
          {children}
        </div>
      </div>
    </div>
  );
}
