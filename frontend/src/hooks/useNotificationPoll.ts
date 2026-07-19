import { useEffect, useRef } from "react";
import { getNotifications, getUnreadCount, streamNotifications } from "@/api/client";
import { playNotification } from "@/lib/sound";
import { useNotificationStore } from "@/store/useNotificationStore";

const RETRY_DELAY_MS = 3500;
const SOUND_RATE_LIMIT_MS = 2000;

export function useNotificationPoll(active: boolean): void {
  const lastSound = useRef(0);

  useEffect(() => {
    if (!active) {
      useNotificationStore.getState().reset();
      return;
    }
    let running = true;
    let controller: AbortController | null = null;

    const refreshDropdown = async () => {
      const list = await getNotifications(8);
      if (running) useNotificationStore.getState().setItems(list.items);
    };

    const poll = async () => {
      while (running) {
        controller = new AbortController();
        try {
          const previous = useNotificationStore.getState().signal;
          const next = await streamNotifications(previous, controller.signal);
          if (!running) return;
          useNotificationStore.getState().setStreamState({ unread: next.unread_count, signal: next.signal });
          if (next.signal > previous && next.preview) {
            const state = useNotificationStore.getState();
            if (!state.muted && Date.now() - lastSound.current >= SOUND_RATE_LIMIT_MS) {
              playNotification();
              lastSound.current = Date.now();
            }
            state.pushToast(next.preview);
            void refreshDropdown().catch(() => {});
          }
        } catch (error) {
          if (!running || (error instanceof DOMException && error.name === "AbortError")) return;
          await new Promise<void>((resolve) => window.setTimeout(resolve, RETRY_DELAY_MS));
        }
      }
    };

    const start = async () => {
      try {
        // Establece la línea base ANTES de abrir el long polling. Antes ambas
        // peticiones competían: si una notificación llegaba en ese intervalo,
        // era la «primera respuesta» y se descartaban tanto toast como sonido.
        const { unread_count, signal } = await getUnreadCount();
        if (!running) return;
        useNotificationStore.getState().setStreamState({ unread: unread_count, signal });
      } catch {
        // Si el estado inicial falla, el stream conserva el reintento normal.
      }
      if (running) void poll();
    };
    void start();
    return () => {
      running = false;
      controller?.abort();
    };
  }, [active]);
}
