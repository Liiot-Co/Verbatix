import { create } from "zustand";
import type { SurveyItem, UploadResult, Metrics, Code, StudyMode } from "../api/types";

export type WizardStage = "upload" | "processing" | "review" | "done";
export type FileStatus = "pending" | "classifying" | "reviewing" | "done" | "error";
export interface FileEntry {
  id: string;
  file: File;
  name: string;
  column: string | null;
  columns: string[];
  roundId: number | null;
  uploadResult: UploadResult | null;
  items: SurveyItem[];
  metrics: Metrics | null;
  status: FileStatus;
  errorMessage?: string;
}

interface Toast {
  id: number;
  message: string;
  type: "success" | "error" | "info";
  actionLabel?: string;
  onAction?: () => void;
}

interface WizardState {
  activeStudyId: number | null;
  setActiveStudyId: (id: number | null) => void;

  activeStudyName: string | null;
  setActiveStudyName: (name: string | null) => void;

  activeStudyMode: StudyMode;
  setActiveStudyMode: (mode: StudyMode) => void;

  stage: WizardStage;
  setStage: (s: WizardStage) => void;

  files: FileEntry[];
  setFiles: (files: FileEntry[]) => void;
  updateFile: (id: string, patch: Partial<FileEntry>) => void;

  activeFileId: string | null;
  setActiveFileId: (id: string | null) => void;

  focusedItemIdx: number;
  setFocusedItemIdx: (i: number) => void;

  loading: boolean;
  setLoading: (v: boolean) => void;

  toasts: Toast[];
  showToast: (
    message: string,
    type?: Toast["type"],
    action?: { label: string; onAction: () => void }
  ) => void;
  dismissToast: (id: number) => void;

  resolveItemsForFile: (
    fileId: string,
    resolved: SurveyItem,
    cascade: SurveyItem[]
  ) => void;

  reopenItemForFile: (fileId: string, item: SurveyItem) => void;

  codebookStudyId: number | null;
  codebook: Code[];
  setCodebook: (studyId: number, codes: Code[]) => void;

  session: SessionStats;
  startSession: () => void;
  recordResolution: (cascadeCount?: number) => void;
  resetSession: () => void;
}

export interface SessionStats {
  startedAt: number | null;
  resolvedCount: number;
  cascadeCount: number;
}

const initialSession: SessionStats = {
  startedAt: null,
  resolvedCount: 0,
  cascadeCount: 0,
};

let toastId = 0;

const ACTIVE_STUDY_KEY = "verbatix:activeStudyId";

function readStoredStudyId(): number | null {
  try {
    const raw = localStorage.getItem(ACTIVE_STUDY_KEY);
    return raw ? Number(raw) : null;
  } catch {
    return null;
  }
}

function writeStoredStudyId(id: number | null) {
  try {
    if (id === null) localStorage.removeItem(ACTIVE_STUDY_KEY);
    else localStorage.setItem(ACTIVE_STUDY_KEY, String(id));
  } catch {
    // storage unavailable (private mode, etc.) — resume just won't persist
  }
}

export const useWizardStore = create<WizardState>((set) => ({
  // Reading synchronously at store creation means the very first render
  // already knows which study to resume — no flash of the study picker.
  activeStudyId: readStoredStudyId(),
  setActiveStudyId: (activeStudyId) => {
    writeStoredStudyId(activeStudyId);
    set({ activeStudyId });
  },

  activeStudyName: null,
  setActiveStudyName: (activeStudyName) => set({ activeStudyName }),

  activeStudyMode: "brands",
  setActiveStudyMode: (activeStudyMode) => set({ activeStudyMode }),

  stage: "upload",
  setStage: (stage) => set({ stage }),

  files: [],
  setFiles: (files) => set({ files }),
  updateFile: (id, patch) =>
    set((s) => ({
      files: s.files.map((f) => (f.id === id ? { ...f, ...patch } : f)),
    })),

  activeFileId: null,
  setActiveFileId: (activeFileId) => set({ activeFileId }),

  focusedItemIdx: 0,
  setFocusedItemIdx: (focusedItemIdx) => set({ focusedItemIdx }),

  loading: false,
  setLoading: (loading) => set({ loading }),

  toasts: [],
  showToast: (message, type = "info", action) => {
    const id = ++toastId;
    const toast: Toast = action
      ? { id, message, type, actionLabel: action.label, onAction: action.onAction }
      : { id, message, type };
    set((s) => ({ toasts: [...s.toasts, toast] }));
    setTimeout(
      () => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
      action ? 5000 : 4000
    );
  },
  dismissToast: (id) =>
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

  resolveItemsForFile: (fileId, resolved, cascade) =>
    set((s) => {
      const resolvedIds = new Set([resolved.id, ...cascade.map((c) => c.id)]);
      return {
        files: s.files.map((f) => {
          if (f.id !== fileId) return f;
          return {
            ...f,
            items: f.items
              .map((item) => {
                if (item.id === resolved.id) return resolved;
                return cascade.find((c) => c.id === item.id) ?? item;
              })
              .filter(
                (item) =>
                  !resolvedIds.has(item.id) || item.status !== "requires_human"
              ),
          };
        }),
      };
    }),

  reopenItemForFile: (fileId, item) =>
    set((s) => ({
      files: s.files.map((f) => {
        if (f.id !== fileId) return f;
        const exists = f.items.some((it) => it.id === item.id);
        return {
          ...f,
          items: exists
            ? f.items.map((it) => (it.id === item.id ? item : it))
            : [item, ...f.items],
        };
      }),
    })),

  codebookStudyId: null,
  codebook: [],
  setCodebook: (studyId, codes) => set({ codebookStudyId: studyId, codebook: codes }),

  session: initialSession,
  startSession: () =>
    set((s) => ({
      session: s.session.startedAt ? s.session : { ...initialSession, startedAt: Date.now() },
    })),
  recordResolution: (cascadeCount = 0) =>
    set((s) => ({
      session: {
        ...s.session,
        resolvedCount: s.session.resolvedCount + 1,
        cascadeCount: s.session.cascadeCount + cascadeCount,
      },
    })),
  resetSession: () => set({ session: initialSession }),
}));
