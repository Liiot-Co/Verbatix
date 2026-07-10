import { create } from "zustand";
import type { SurveyItem, UploadResult, Metrics } from "../api/types";

export type WizardStage = "upload" | "configure" | "processing" | "review" | "done";
export type FileStatus = "pending" | "classifying" | "reviewing" | "done" | "error";
export type AppView = "project" | "history" | "codebook";

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
}

interface WizardState {
  view: AppView;
  setView: (v: AppView) => void;

  activeStudyId: number | null;
  setActiveStudyId: (id: number | null) => void;

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
  showToast: (message: string, type?: Toast["type"]) => void;
  dismissToast: (id: number) => void;

  resolveItemsForFile: (
    fileId: string,
    resolved: SurveyItem,
    cascade: SurveyItem[]
  ) => void;
}

let toastId = 0;

export const useWizardStore = create<WizardState>((set) => ({
  view: "project",
  setView: (view) => set({ view }),

  activeStudyId: null,
  setActiveStudyId: (activeStudyId) => set({ activeStudyId }),

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
  showToast: (message, type = "info") => {
    const id = ++toastId;
    set((s) => ({ toasts: [...s.toasts, { id, message, type }] }));
    setTimeout(
      () => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
      4000
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
}));
