import { create } from "zustand";

interface Toast {
  id: number;
  message: string;
  type: "success" | "error" | "info";
  actionLabel?: string;
  onAction?: () => void;
}

interface VerbatixState {
  activeProjectId: string | null;
  setActiveProjectId: (id: string | null) => void;

  toasts: Toast[];
  showToast: (
    message: string,
    type?: Toast["type"],
    action?: { label: string; onAction: () => void }
  ) => void;
  dismissToast: (id: number) => void;
}

let toastId = 0;

const ACTIVE_PROJECT_KEY = "verbatix:activeProjectId";

function readStoredProjectId(): string | null {
  try {
    return localStorage.getItem(ACTIVE_PROJECT_KEY);
  } catch {
    return null;
  }
}

function writeStoredProjectId(id: string | null) {
  try {
    if (id === null) localStorage.removeItem(ACTIVE_PROJECT_KEY);
    else localStorage.setItem(ACTIVE_PROJECT_KEY, id);
  } catch {
    // storage unavailable (private mode, etc.) — resume just won't persist
  }
}

export const useVerbatixStore = create<VerbatixState>((set) => ({
  activeProjectId: readStoredProjectId(),
  setActiveProjectId: (activeProjectId) => {
    writeStoredProjectId(activeProjectId);
    set({ activeProjectId });
  },

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
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));
