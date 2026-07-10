import { create } from "zustand";
import type { Round, SurveyItem, Metrics, UploadResult } from "../api/types";

export type Step = 1 | 2 | 3;

interface Toast {
  id: number;
  message: string;
  type: "success" | "error" | "info";
}

interface AppState {
  step: Step;
  setStep: (s: Step) => void;

  rounds: Round[];
  setRounds: (r: Round[]) => void;
  activeRound: Round | null;
  setActiveRound: (r: Round | null) => void;

  uploadResult: UploadResult | null;
  setUploadResult: (r: UploadResult) => void;

  items: SurveyItem[];
  setItems: (items: SurveyItem[]) => void;
  resolveItems: (resolved: SurveyItem, cascade: SurveyItem[]) => void;

  metrics: Metrics | null;
  setMetrics: (m: Metrics) => void;

  loading: boolean;
  setLoading: (v: boolean) => void;

  focusedItemIdx: number;
  setFocusedItemIdx: (i: number) => void;

  toasts: Toast[];
  showToast: (message: string, type?: Toast["type"]) => void;
  dismissToast: (id: number) => void;
}

let toastId = 0;

export const useAppStore = create<AppState>((set) => ({
  step: 1,
  setStep: (step) => set({ step }),

  rounds: [],
  setRounds: (rounds) => set({ rounds }),
  activeRound: null,
  setActiveRound: (activeRound) => set({ activeRound }),

  uploadResult: null,
  setUploadResult: (uploadResult) =>
    set({ uploadResult, items: uploadResult.items }),

  items: [],
  setItems: (items) => set({ items }),
  resolveItems: (resolved, cascade) =>
    set((s) => {
      const resolvedIds = new Set([resolved.id, ...cascade.map((c) => c.id)]);
      return {
        items: s.items.map((item) => {
          if (item.id === resolved.id) return resolved;
          const cascadeItem = cascade.find((c) => c.id === item.id);
          return cascadeItem ?? item;
        }).filter((item) => !resolvedIds.has(item.id) || item.status !== "requires_human"),
      };
    }),

  metrics: null,
  setMetrics: (metrics) => set({ metrics }),

  loading: false,
  setLoading: (loading) => set({ loading }),

  focusedItemIdx: 0,
  setFocusedItemIdx: (focusedItemIdx) => set({ focusedItemIdx }),

  toasts: [],
  showToast: (message, type = "info") => {
    const id = ++toastId;
    set((s) => ({ toasts: [...s.toasts, { id, message, type }] }));
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 4000);
  },
  dismissToast: (id) =>
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));
