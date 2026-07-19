import { motion } from "framer-motion";
import { useState } from "react";
import { CheckCircle2, Clock3, LogOut, RefreshCw, ShieldAlert } from "lucide-react";
import { logoutSession } from "@/api/client";
import RoleBadge from "@/components/RoleBadge";
import { useVerbatixStore } from "@/store/useVerbatixStore";

export default function AccountStatePage({ state }: { state: "pending" | "suspended" }) {
  const { user, hydrateSession, logout } = useVerbatixStore();
  const [refreshing, setRefreshing] = useState(false);
  const pending = state === "pending";
  const suspended = state === "suspended";
  const Icon = suspended ? ShieldAlert : Clock3;
  return <div className="min-h-screen bg-p-bg grid place-items-center px-4 relative overflow-hidden">
    <div aria-hidden className="ambient-wash pointer-events-none fixed inset-0 -z-10" />
    <motion.section initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} className="card p-7 sm:p-9 max-w-lg w-full">
      <div className="w-14 h-14 rounded-2xl bg-p-accent-soft text-p-accent grid place-items-center mb-5"><Icon className="w-7 h-7" /></div>
      <h1 className="font-heading text-2xl font-semibold text-p-text">{pending ? "Estamos preparando tu espacio" : "Tu acceso está suspendido"}</h1>
      <p className="text-sm text-p-text-muted mt-2">{pending ? "Tu cuenta fue creada y el código de recuperación quedó en tus manos. Un administrador debe aprobar tus roles y proyectos." : "Tu sesión no puede acceder al espacio de trabajo. Contacta a un administrador para revisar el estado de la cuenta."}</p>
      {user?.roles.length ? <div className="flex gap-2 mt-4">{user.roles.map((role) => <RoleBadge key={role} role={role} />)}</div> : null}
      {pending && <div className="mt-6 space-y-3"><div className="flex gap-3 text-sm text-p-text"><CheckCircle2 className="w-5 h-5 text-p-success" />Cuenta y recuperación configuradas</div><div className="flex gap-3 text-sm text-p-text-muted"><Clock3 className="w-5 h-5 text-p-warning" />Aprobación, roles y proyectos pendientes</div></div>}
      <div className="flex flex-col sm:flex-row gap-2 mt-7">
        {!suspended && <button disabled={refreshing} onClick={async () => { setRefreshing(true); try { await hydrateSession(); } finally { setRefreshing(false); } }} className="btn-primary justify-center disabled:opacity-60"><RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin" : ""}`} />{refreshing ? "Actualizando…" : "Actualizar estado"}</button>}
        <button onClick={async () => { try { await logoutSession(); } finally { logout(); window.location.href = "/login"; } }} className="btn-ghost justify-center"><LogOut className="w-4 h-4" />Cerrar sesión</button>
      </div>
    </motion.section>
  </div>;
}
