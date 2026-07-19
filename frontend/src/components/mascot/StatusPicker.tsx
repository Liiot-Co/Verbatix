import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { motion, useReducedMotion } from "framer-motion";
import { setPresence } from "@/api/client";
import { PRESENCE_CATALOG, PRESENCE_ORDER, type PresenceStatus } from "@/lib/presence";
import { playTick } from "@/lib/sound";
import { useVerbatixStore } from "@/store/useVerbatixStore";

interface StatusPickerProps {
  status: PresenceStatus;
  onClose: () => void;
  onChanged?: () => void;
  position?: "above" | "below";
  variant?: "popover" | "floating";
  anchorRef?: RefObject<HTMLElement | null>;
}

export default function StatusPicker({
  status,
  onClose,
  onChanged,
  position = "above",
  variant = "popover",
  anchorRef,
}: StatusPickerProps) {
  const pickerRef = useRef<HTMLDivElement>(null);
  const buttonsRef = useRef<Array<HTMLButtonElement | null>>([]);
  const reducedMotion = useReducedMotion();
  const [anchorBottom, setAnchorBottom] = useState<number | null>(null);
  const setPresenceLocal = useVerbatixStore((state) => state.setPresenceLocal);
  const showToast = useVerbatixStore((state) => state.showToast);

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (
        pickerRef.current &&
        !pickerRef.current.contains(target) &&
        !anchorRef?.current?.contains(target)
      ) onClose();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose]);

  useLayoutEffect(() => {
    if (!anchorRef?.current || variant !== "popover") return;
    const updatePosition = () => {
      const rect = anchorRef.current?.getBoundingClientRect();
      if (rect) setAnchorBottom(Math.max(12, window.innerHeight - rect.top + 10));
    };
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [anchorRef, variant]);

  const choose = async (next: PresenceStatus) => {
    if (next === status) {
      onClose();
      return;
    }
    const previousStatus = status;
    const previousChangedAt = useVerbatixStore.getState().user?.presence_changed_at ?? null;
    const optimisticChangedAt = new Date().toISOString();
    setPresenceLocal(next, optimisticChangedAt);
    localStorage.setItem("verbatix:mascot-hint", "1");
    onChanged?.();
    playTick();
    onClose();
    try {
      const result = await setPresence(next);
      setPresenceLocal(result.status, result.changed_at);
    } catch {
      setPresenceLocal(previousStatus, previousChangedAt);
      showToast("No se pudo actualizar tu estado.", "error");
    }
  };

  const onCardKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!(["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft"] as string[]).includes(event.key)) return;
    event.preventDefault();
    const offset = event.key === "ArrowDown" || event.key === "ArrowRight" ? 1 : -1;
    const next = (index + offset + PRESENCE_ORDER.length) % PRESENCE_ORDER.length;
    buttonsRef.current[next]?.focus();
  };

  const floating = variant === "floating";
  const anchorStyle = anchorBottom === null ? {} : { bottom: anchorBottom, left: 8 };
  const picker = (
    <motion.div
      ref={pickerRef}
      role="dialog"
      aria-label="Seleccionar estado de presencia"
      initial={{ opacity: 0, scale: reducedMotion ? 1 : 0.96, y: reducedMotion ? 0 : position === "above" ? 6 : -6 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: reducedMotion ? 1 : 0.96, y: reducedMotion ? 0 : position === "above" ? 6 : -6 }}
      transition={reducedMotion ? { duration: 0.16 } : { type: "spring", stiffness: 360, damping: 28 }}
      style={anchorStyle}
      className={[
        `z-[60] ${floating ? "w-[min(26rem,calc(100vw-1.5rem))]" : "w-[min(22rem,calc(100vw-1.5rem))]"}`,
        floating
          ? "fixed bottom-5 right-5 rounded-2xl border border-p-border bg-p-surface p-3 shadow-xl"
          : anchorRef
            ? "fixed rounded-2xl border border-p-border bg-p-surface p-3 shadow-xl"
            : `absolute rounded-2xl border border-p-border bg-p-surface p-3 shadow-xl ${position === "above" ? "bottom-full mb-2 left-0" : "top-full mt-2 right-0"}`,
      ].join(" ")}
    >
      <p className={`font-heading font-semibold text-p-text ${floating ? "px-1 pb-2 text-right text-xs" : "px-1 pb-2 text-sm"}`}>¿Qué estás haciendo?</p>
      <div className={`grid gap-2 ${floating ? "grid-cols-5" : "grid-cols-2"}`} role="group" aria-label="Estados disponibles">
        {PRESENCE_ORDER.map((item, index) => {
          const meta = PRESENCE_CATALOG[item];
          const Icon = meta.icon;
          const selected = item === status;
          const cardGestureProps = reducedMotion
            ? {}
            : { whileHover: { y: -2 }, whileTap: { scale: 0.98 } };
          return (
            <motion.button
              key={item}
              ref={(element) => { buttonsRef.current[index] = element; }}
              type="button"
              onClick={() => void choose(item)}
              onKeyDown={(event) => onCardKeyDown(event, index)}
              {...cardGestureProps}
              className={[
                "relative flex overflow-hidden rounded-xl border text-left transition-colors",
                floating ? "min-h-[5.75rem] flex-col justify-center gap-1 border-transparent bg-transparent p-1 hover:bg-p-bg-subtle/50" : "min-h-24 items-center gap-2 p-2",
                selected ? "border-p-accent ring-2 ring-p-accent/35" : floating ? "hover:border-p-border-mid" : "border-p-border hover:border-p-border-mid hover:bg-p-bg-subtle/40",
              ].join(" ")}
              aria-pressed={selected}
            >
              <img src={meta.art} alt="" className={`${floating ? "h-[3.25rem] w-[3.25rem]" : "h-14 w-14"} shrink-0 object-contain`} />
              <span className={`inline-flex min-w-0 items-center gap-1 rounded-full px-2 py-1 text-[11px] font-semibold ${meta.tint}`}>
                <Icon className="h-3 w-3 shrink-0" />
                <span className={floating ? "sr-only" : "truncate"}>{meta.label}</span>
              </span>
            </motion.button>
          );
        })}
      </div>
    </motion.div>
  );

  return anchorRef || floating ? createPortal(picker, document.body) : picker;
}
