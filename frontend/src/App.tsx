import { useEffect, useRef } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate, Outlet } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Upload, ScanSearch, LayoutDashboard, ChevronLeft, Check } from "lucide-react";
import { useWizardStore, type WizardStage } from "@/store/useWizardStore";
import { useWizardOrchestrator } from "@/hooks/useWizardOrchestrator";
import { getRounds } from "@/api/client";
import AppShell from "@/components/AppShell";
import CodebookView from "@/components/CodebookView";
import HistoryView from "@/components/HistoryView";
import StudyPicker from "@/components/StudyPicker";
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
    <nav className="flex items-center gap-1.5" aria-label="Progreso">
      {STEPS.map((s, i) => {
        const active = group === s.num;
        const done   = group > s.num;
        const Icon   = done ? Check : s.icon;
        return (
          <div key={s.num} className="flex items-center gap-1.5">
            <span
              className={[
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                active
                  ? "bg-p-accent text-white shadow-sm scale-105"
                  : done
                  ? "bg-p-accent-soft text-p-accent"
                  : "text-p-text-faint",
              ].join(" ")}
            >
              <Icon className="w-3.5 h-3.5" />
              {s.label}
              {active && s.num === 2 && fileIdx && files.length > 1 && (
                <span className="ml-1 opacity-70">
                  {fileIdx}/{files.length}
                </span>
              )}
            </span>
            {i < STEPS.length - 1 && (
              <div className="w-6 h-px rounded-full bg-p-border overflow-hidden">
                <div
                  className={[
                    "h-full bg-p-accent transition-all duration-300",
                    done ? "w-full" : "w-0",
                  ].join(" ")}
                />
              </div>
            )}
          </div>
        );
      })}
    </nav>
  );
}

function StudyHeader({ onBack, children }: { onBack: () => void; children?: React.ReactNode }) {
  const activeStudyName = useWizardStore((s) => s.activeStudyName);
  return (
    <header className="shrink-0 h-[52px] px-5 border-b border-p-border bg-p-surface flex items-center gap-3">
      <button
        onClick={onBack}
        className="flex items-center gap-1 text-xs text-p-text-muted hover:text-p-text truncate transition-colors"
      >
        <ChevronLeft className="w-3.5 h-3.5 shrink-0" />
        {activeStudyName ?? "Estudio"}
      </button>
      <div className="ml-auto">{children}</div>
    </header>
  );
}

const STAGE_FROM_PATH: Record<string, WizardStage> = {
  "/project/upload": "upload",
  "/project/processing": "processing",
  "/project/review": "review",
  "/project/dashboard": "done",
};

function ProjectLayout() {
  const stage    = useWizardStore((s) => s.stage);
  const activeStudyId = useWizardStore((s) => s.activeStudyId);
  const setActiveStudyId = useWizardStore((s) => s.setActiveStudyId);
  const setStage = useWizardStore((s) => s.setStage);

  const { resetWizard } = useWizardOrchestrator();
  const navigate = useNavigate();
  const location = useLocation();

  const isReview = location.pathname === "/project/review";

  // Sync stage → URL (orchestrator-driven transitions)
  const prevStageRef = useRef(stage);
  useEffect(() => {
    if (prevStageRef.current === stage) return;
    prevStageRef.current = stage;
    const stageToPath: Record<WizardStage, string> = {
      upload: "/project/upload",
      processing: "/project/processing",
      review: "/project/review",
      done: "/project/dashboard",
    };
    const target = stageToPath[stage];
    if (target && location.pathname !== target) {
      navigate(target, { replace: true });
    }
  }, [stage, navigate, location.pathname]);

  // Sync URL → stage (direct navigation / sidebar clicks)
  const prevPathRef = useRef(location.pathname);
  useEffect(() => {
    if (prevPathRef.current === location.pathname) return;
    prevPathRef.current = location.pathname;
    const expected = STAGE_FROM_PATH[location.pathname];
    if (expected && expected !== stage) {
      setStage(expected);
    }
  }, [location.pathname, stage, setStage]);

  // Initial mount: sync URL → stage
  const initialRef = useRef(true);
  useEffect(() => {
    if (!initialRef.current) return;
    initialRef.current = false;
    const expected = STAGE_FROM_PATH[location.pathname];
    if (expected && expected !== stage) {
      setStage(expected);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!activeStudyId) {
    return (
      <main className="flex-1 px-6 py-8 overflow-y-auto min-h-0">
        <StudyPicker />
      </main>
    );
  }

  const backToStudies = () => {
    resetWizard();
    setActiveStudyId(null);
  };

  return (
    <>
      <StudyHeader onBack={backToStudies}>
        <WizardProgress />
      </StudyHeader>
      <main className={[
        "flex-1 px-6 py-6 min-h-0",
        isReview ? "overflow-hidden flex flex-col" : "overflow-y-auto py-8",
      ].join(" ")}>
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className={isReview ? "flex-1 min-h-0" : undefined}
          >
            <Outlet />
          </motion.div>
        </AnimatePresence>
      </main>
    </>
  );
}

function UploadPage() {
  return <UploadStage />;
}

function ProcessingPage() {
  const files = useWizardStore((s) => s.files);
  const activeFileId = useWizardStore((s) => s.activeFileId);
  const activeEntry = files.find((f) => f.id === activeFileId);
  return (
    <Loader text={`Clasificando "${activeEntry?.name ?? "archivo"}"...`} />
  );
}

function ReviewPage() {
  const { advanceToNextFile } = useWizardOrchestrator();
  return <ReviewStage onAdvance={advanceToNextFile} />;
}

function DashboardPage() {
  const { resetWizard } = useWizardOrchestrator();
  return <DashboardStage onReset={resetWizard} />;
}

export default function App() {
  const activeStudyId = useWizardStore((s) => s.activeStudyId);
  const files          = useWizardStore((s) => s.files);
  const { continueRound } = useWizardOrchestrator();

  const attemptedRef = useRef(false);
  useEffect(() => {
    if (attemptedRef.current) return;
    attemptedRef.current = true;
    if (!activeStudyId || files.length > 0) return;

    getRounds()
      .then((rounds) => {
        const pending = rounds.find(
          (r) => r.study_id === activeStudyId && (r.requires_human ?? 0) > 0
        );
        if (pending) continueRound(pending);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Navigate to="/project/upload" replace />} />
        <Route path="/project" element={<ProjectLayout />}>
          <Route index element={<Navigate to="upload" replace />} />
          <Route path="upload" element={<UploadPage />} />
          <Route path="processing" element={<ProcessingPage />} />
          <Route path="review" element={<ReviewPage />} />
          <Route path="dashboard" element={<DashboardPage />} />
        </Route>
        <Route path="/history" element={<HistoryView />} />
        <Route path="/codebook" element={<CodebookView />} />
      </Routes>
      <ToastStack />
    </AppShell>
  );
}
