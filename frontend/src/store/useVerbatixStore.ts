import { create } from "zustand";
import type { UserProfile } from "@/api/types";

interface Toast {
  id: number;
  message: string;
  type: "success" | "error" | "info";
  actionLabel?: string;
  onAction?: () => void;
}

interface VerbatixState {
  /* Auth */
  token: string | null;
  user: UserProfile | null;
  isAuthenticated: boolean;
  setAuth: (token: string, user: UserProfile) => void;
  logout: () => void;

  /* Navigation */
  activeProjectId: string | null;
  setActiveProjectId: (id: string | null) => void;

  /* Toasts */
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
const TOKEN_KEY = "verbatix:token";
const USER_KEY = "verbatix:user";

function readStored<T>(key: string, fallback: T): T {
  try {
    const val = localStorage.getItem(key);
    return val ? (JSON.parse(val) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeStored(key: string, val: unknown) {
  try {
    if (val === null || val === undefined) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(val));
  } catch {
    // storage unavailable
  }
}

export const useVerbatixStore = create<VerbatixState>((set) => ({
  token: readStored<string | null>(TOKEN_KEY, null),
  user: readStored<UserProfile | null>(USER_KEY, null),
  isAuthenticated: !!readStored<string | null>(TOKEN_KEY, null),

  setAuth: (token, user) => {
    writeStored(TOKEN_KEY, token);
    writeStored(USER_KEY, user);
    set({ token, user, isAuthenticated: true });
  },

  logout: () => {
    writeStored(TOKEN_KEY, null);
    writeStored(USER_KEY, null);
    set({ token: null, user: null, isAuthenticated: false });
  },

  activeProjectId: readStored<string | null>(ACTIVE_PROJECT_KEY, null),
  setActiveProjectId: (activeProjectId) => {
    writeStored(ACTIVE_PROJECT_KEY, activeProjectId);
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
