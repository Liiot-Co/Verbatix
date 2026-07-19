import { create } from "zustand";
import type { UserProfile } from "@/api/types";
import { getMe } from "@/api/client";
import { readAuthToken, writeAuthToken } from "@/lib/tokenStorage";

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
  sessionReady: boolean;
  setAuth: (token: string, user: UserProfile) => void;
  hydrateSession: () => Promise<void>;
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
const MAX_VISIBLE_TOASTS = 5;

const ACTIVE_PROJECT_KEY = "verbatix:activeProjectId";
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
  token: readAuthToken(),
  user: readStored<UserProfile | null>(USER_KEY, null),
  isAuthenticated: false,
  sessionReady: false,

  setAuth: (token, user) => {
    writeAuthToken(token);
    writeStored(USER_KEY, user);
    set({ token, user, isAuthenticated: true, sessionReady: true });
  },

  hydrateSession: async () => {
    const token = readAuthToken();
    if (!token) {
      set({ token: null, user: null, isAuthenticated: false, sessionReady: true });
      return;
    }
    try {
      const user = await getMe();
      writeStored(USER_KEY, user);
      set({ token, user, isAuthenticated: true, sessionReady: true });
    } catch {
      writeAuthToken(null);
      writeStored(USER_KEY, null);
      set({ token: null, user: null, isAuthenticated: false, sessionReady: true });
    }
  },

  logout: () => {
    writeAuthToken(null);
    writeStored(USER_KEY, null);
    set({ token: null, user: null, isAuthenticated: false, sessionReady: true });
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
    set((s) => {
      const toasts = [...s.toasts, toast];
      if (toasts.length > MAX_VISIBLE_TOASTS) {
        return { toasts: toasts.slice(toasts.length - MAX_VISIBLE_TOASTS) };
      }
      return { toasts };
    });
    setTimeout(
      () => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
      action ? 5000 : 4000
    );
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));
