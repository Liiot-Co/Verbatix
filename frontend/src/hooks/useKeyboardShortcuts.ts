import { useEffect } from "react";

export interface PageShortcut {
  key: string;
  meta?: boolean;
  ctrl?: boolean;
  shift?: boolean;
  alt?: boolean;
  action: () => void;
  description: string;
  category: string;
  /** Explicitly allow firing while a text input/select/textarea is focused. */
  allowInInput?: boolean;
}

const registry = new Map<string, PageShortcut[]>();
const isMac = navigator.platform.includes("Mac");

/** Register (or replace) the shortcut list for a page key, e.g. "global", "verbatims". */
export function registerShortcuts(pageKey: string, shortcuts: PageShortcut[]): void {
  registry.set(pageKey, shortcuts);
}

/** OS-aware modifier label. Returns "⌘" on Mac, "Ctrl" on Windows/Linux. */
export function modLabel(): string {
  return isMac ? "⌘" : "Ctrl";
}

/** OS-aware shortcut hint, e.g. "⌘⇧D" on Mac or "Ctrl+⇧D" on Windows. */
export function formatShortcut(s: Pick<PageShortcut, "key" | "meta" | "ctrl" | "shift" | "alt">): string {
  const parts: string[] = [];
  if (s.meta) parts.push(isMac ? "⌘" : "Ctrl");
  if (s.ctrl) parts.push("Ctrl");
  if (s.shift) parts.push("⇧");
  if (s.alt) parts.push(isMac ? "⌥" : "Alt");
  parts.push(s.key.length === 1 ? s.key.toUpperCase() : s.key);
  return parts.join(isMac ? "" : "+");
}

function isTypingTarget(el: EventTarget | null): boolean {
  return (
    el instanceof HTMLInputElement ||
    el instanceof HTMLTextAreaElement ||
    el instanceof HTMLSelectElement ||
    (el instanceof HTMLElement && el.isContentEditable)
  );
}

/** Activates the shortcuts registered under `pageKey` for as long as the component is mounted. */
export function useKeyboardShortcuts(pageKey: string): void {
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const typing = isTypingTarget(e.target);
      for (const s of registry.get(pageKey) ?? []) {
        if (e.key.toLowerCase() !== s.key.toLowerCase()) continue;
        if (!!s.meta !== (isMac ? e.metaKey : e.ctrlKey)) continue;
        if (!!s.shift !== e.shiftKey) continue;
        if (!!s.alt !== e.altKey) continue;

        if (typing) {
          const hasModifier = !!(s.meta || s.ctrl || s.alt);
          if (s.allowInInput === false) continue;
          if (!hasModifier && s.key !== "Escape" && s.allowInInput !== true) continue;
        }

        e.preventDefault();
        s.action();
        return;
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [pageKey]);
}
