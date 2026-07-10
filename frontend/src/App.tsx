import { AnimatePresence, motion } from "framer-motion";
import { Upload, ScanSearch, LayoutDashboard } from "lucide-react";
import { useWizardStore, type WizardStage } from "@/store/useWizardStore";
import { useWizardOrchestrator } from "@/hooks/useWizardOrchestrator";
import AppShell from "@/components/AppShell";
import CodebookView from "@/components/CodebookView";
import HistoryView from "@/components/HistoryView";
import UploadStage from "@/components/UploadStage";
import ReviewStage from "@/components/ReviewStage";
import DashboardStage from "@/components/DashboardStage";
import Loader from "@/components/Loader";
import ToastStack from "@/components/ToastStack";

type StageGroup = 1 | 2 | 3;

function stageToGroup(stage: WizardStage): StageGroup {
  if (stage === "upload") return 1;
  if (stage === "processing" || stage === "review") return 2;
  return 3;
}

const STEPS = [
  { num: 1 as StageGroup, label: "Carga",    icon: Upload },
  { num: 2 as StageGroup, label: "Revisión", icon: ScanSearch },
  { num: 3 as StageGroup, label: "Dashboard",icon: LayoutDashboard },
];

function WizardProgress() {
  const stage       = useWizardStore((s) => s.stage);
  const files       = useWizardStore((s) => s.files);
  const activeFileId = useWizardStore((s) => s.activeFileId);

  const group    = stageToGroup(stage);
  const fileIdx  = activeFileId
    ? files.findIndex((f) => f.id === activeFileId) + 1
    : null;

  return (
    <nav className="flex items-center gap-1" aria-label="Progreso">
      {STEPS.map((s, i) => {
        const active = group === s.num;
        const done   = group > s.num;
        return (
          <div key={s.num} className="flex items-center gap-1">
            <span
              className={[
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                active
                  ? "bg-p-accent text-white shadow-sm"
                  : done
                  ? "text-p-accent"
                  : "text-p-text-faint",
              ].join(" ")}
            >
              <s.icon className="w-3.5 h-3.5" />
              {s.label}
              {active && s.num === 2 && fileIdx && files.length > 1 && (
                <span className="ml-1 opacity-70">
                  {fileIdx}/{files.length}
                </span>
              )}
            </span>
            {i < STEPS.length - 1 && (
              <div
                className={`w-6 h-px ${
                  done ? "bg-p-accent/40" : "bg-p-border"
                }`}
              />
            )}
          </div>
        );
      })}
    </nav>
  );
}

function ProjectView() {
  const stage    = useWizardStore((s) => s.stage);
  const files    = useWizardStore((s) => s.files);
  const activeFileId = useWizardStore((s) => s.activeFileId);
  const activeStudyName = useWizardStore((s) => s.activeStudyName);

  const { advanceToNextFile, resetWizard } = useWizardOrchestrator();

  const activeEntry = files.find((f) => f.id === activeFileId);

  return (
    <>
      {/* Top bar — left anchor orients the user in the active study */}
      <header className="shrink-0 h-[52px] px-5 border-b border-p-border bg-p-surface flex items-center gap-3">
        <span className="text-xs text-p-text-muted truncate">
          {activeStudyName ?? "Proyecto"}
        </span>
        <div className="ml-auto">
          <WizardProgress />
        </div>
      </header>

      {/* Main content */}
      <main className={[
        "flex-1 px-6 py-6 min-h-0",
        stage === "review" ? "overflow-hidden flex flex-col" : "overflow-y-auto py-8",
      ].join(" ")}>
        <AnimatePresence mode="wait">
          <motion.div
            key={stage}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className={stage === "review" ? "flex-1 min-h-0" : undefined}
          >
            {stage === "upload" && <UploadStage />}
            {stage === "processing" && (
              <Loader
                text={`Clasificando "${activeEntry?.name ?? "archivo"}"...`}
              />
            )}
            {stage === "review" && (
              <ReviewStage onAdvance={advanceToNextFile} />
            )}
            {stage === "done" && <DashboardStage onReset={resetWizard} />}
          </motion.div>
        </AnimatePresence>
      </main>
    </>
  );
}

export default function App() {
  const view = useWizardStore((s) => s.view);

  return (
    <AppShell>
      {view === "project" && <ProjectView />}
      {view === "history" && <HistoryView />}
      {view === "codebook" && <CodebookView />}
      <ToastStack />
    </AppShell>
  );
}
