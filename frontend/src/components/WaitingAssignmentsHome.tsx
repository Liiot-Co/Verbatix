import { useState } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Inbox, RefreshCw, Sparkles } from "lucide-react";
import RoleBadge from "@/components/RoleBadge";
import MascotAvatar from "@/components/mascot/MascotAvatar";
import StatusPicker from "@/components/mascot/StatusPicker";
import { PRESENCE_CATALOG, PRESENCE_ORDER, type PresenceStatus } from "@/lib/presence";
import { useVerbatixStore } from "@/store/useVerbatixStore";

export default function WaitingAssignmentsHome() {
  const { user, hydrateSession } = useVerbatixStore();
  const reduceMotion = useReducedMotion();
  const [refreshing, setRefreshing] = useState(false);
  const [presenceOpen, setPresenceOpen] = useState(false);
  const presenceStatus: PresenceStatus = user?.presence_status ?? "disponible";
  const firstName = user?.name?.trim().split(/\s+/)[0] ?? null;

  const refresh = async () => {
    setRefreshing(true);
    try {
      await hydrateSession();
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="relative mx-auto flex min-h-[calc(100vh-4rem)] max-w-3xl flex-col items-center justify-center px-2 py-8 text-center">
      <motion.div
        aria-hidden
        className="pointer-events-none absolute inset-x-8 top-1/4 h-64 rounded-full bg-p-accent/10 blur-3xl"
        {...(!reduceMotion
          ? {
              animate: { opacity: [0.35, 0.55, 0.35], scale: [0.96, 1.04, 0.96] },
              transition: { duration: 6, repeat: Infinity, ease: "easeInOut" as const },
            }
          : {})}
      />

      <motion.div
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 280, damping: 28 }}
        className="relative z-10 flex w-full flex-col items-center gap-6"
      >
        <div className="relative">
          <motion.div
            aria-hidden
            className="absolute inset-[-18%] rounded-full border border-p-accent/25"
            {...(!reduceMotion
              ? {
                  animate: { scale: [1, 1.08, 1], opacity: [0.55, 0.15, 0.55] },
                  transition: { duration: 3.2, repeat: Infinity, ease: "easeInOut" as const },
                }
              : {})}
          />
          <MascotAvatar
            status={presenceStatus}
            size="lg"
            onClick={() => setPresenceOpen(true)}
            title={`Cambiar estado — ${PRESENCE_CATALOG[presenceStatus].label}`}
          />
          <AnimatePresence>
            {presenceOpen && (
              <StatusPicker
                status={presenceStatus}
                onClose={() => setPresenceOpen(false)}
                variant="floating"
              />
            )}
          </AnimatePresence>
        </div>

        <div className="space-y-2">
          <div className="inline-flex items-center gap-1.5 rounded-full bg-p-accent-soft px-3 py-1 text-[11px] font-medium text-p-accent">
            <Sparkles className="h-3.5 w-3.5" />
            Listo para arrancar
          </div>
          <h1 className="font-heading text-3xl font-semibold tracking-tight text-p-text sm:text-4xl">
            {firstName ? `${firstName}, ` : ""}esperando asignaciones
          </h1>
          <p className="mx-auto max-w-md text-sm leading-relaxed text-p-text-muted">
            Tu rol ya está activo. En cuanto un administrador te asigne un proyecto,
            aparecerá aquí. Mientras tanto puedes revisar la bandeja y definir cómo te encuentran.
          </p>
        </div>

        {user?.roles.length ? (
          <div className="flex flex-wrap items-center justify-center gap-2">
            {user.roles.map((role) => (
              <RoleBadge key={role} role={role} />
            ))}
          </div>
        ) : null}

        <div className="w-full max-w-lg">
          <div className="mb-2 font-subtitle text-[10px] uppercase tracking-[0.2em] text-p-text-faint">
            Tu estado ahora
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {PRESENCE_ORDER.map((status, index) => {
              const meta = PRESENCE_CATALOG[status];
              const Icon = meta.icon;
              const active = status === presenceStatus;
              return (
                <motion.button
                  key={status}
                  type="button"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.04 * index, type: "spring", stiffness: 360, damping: 24 }}
                  onClick={() => setPresenceOpen(true)}
                  className={[
                    "rounded-xl border px-2.5 py-2.5 text-left transition-colors",
                    active
                      ? "border-p-accent/40 bg-p-accent-soft shadow-sm"
                      : "border-p-border bg-p-surface/70 hover:border-p-accent/25 hover:bg-p-bg-subtle/80",
                  ].join(" ")}
                >
                  <div className="flex items-center gap-1.5">
                    <span className={`h-1.5 w-1.5 rounded-full ${meta.dotClass}`} />
                    <Icon className={`h-3.5 w-3.5 ${active ? "text-p-accent" : "text-p-text-faint"}`} />
                  </div>
                  <div className={`mt-1.5 text-[11px] font-medium leading-tight ${active ? "text-p-accent" : "text-p-text-muted"}`}>
                    {meta.label}
                  </div>
                </motion.button>
              );
            })}
          </div>
        </div>

        <div className="flex w-full max-w-sm flex-col gap-2 sm:flex-row sm:justify-center">
          <Link to="/notifications" className="btn-primary justify-center">
            <Inbox className="h-4 w-4" />
            Ir a la bandeja
          </Link>
          <button
            type="button"
            disabled={refreshing}
            onClick={() => void refresh()}
            className="btn-ghost justify-center disabled:opacity-60"
          >
            <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
            {refreshing ? "Actualizando…" : "Actualizar estado"}
          </button>
        </div>

        <p className="text-[11px] text-p-text-faint">
          Tip: haz clic en el muñeco para cambiar tu presencia — el equipo lo verá al asignarte.
        </p>
      </motion.div>
    </div>
  );
}
