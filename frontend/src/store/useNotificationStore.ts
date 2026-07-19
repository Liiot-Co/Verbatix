import { create } from "zustand";
import type { Notification, NotificationPreview } from "@/api/types";

export interface NotifToast {
  id: number;
  notification: NotificationPreview;
}

interface NotificationState {
  unread: number;
  signal: number;
  muted: boolean;
  items: Notification[];
  toasts: NotifToast[];
  setStreamState: (state: { unread: number; signal: number }) => void;
  setItems: (items: Notification[]) => void;
  pushToast: (notification: NotificationPreview) => void;
  dismissToast: (id: number) => void;
  toggleMuted: () => void;
  reset: () => void;
}

const MUTE_KEY = "verbatix:notif-muted";
let toastId = 0;

function getMuted(): boolean {
  try {
    return localStorage.getItem(MUTE_KEY) === "1";
  } catch {
    return false;
  }
}

export const useNotificationStore = create<NotificationState>((set) => ({
  unread: 0,
  signal: 0,
  muted: getMuted(),
  items: [],
  toasts: [],
  setStreamState: ({ unread, signal }) => set({ unread, signal }),
  setItems: (items) => set({ items }),
  pushToast: (notification) => {
    const id = ++toastId;
    set((state) => ({ toasts: [...state.toasts, { id, notification }].slice(-4) }));
    window.setTimeout(() => set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) })), 5000);
  },
  dismissToast: (id) => set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) })),
  toggleMuted: () => set((state) => {
    const muted = !state.muted;
    try { localStorage.setItem(MUTE_KEY, muted ? "1" : "0"); } catch { /* storage unavailable */ }
    return { muted };
  }),
  reset: () => set({ unread: 0, signal: 0, items: [], toasts: [] }),
}));
