import { useEffect, useMemo } from "react";
import { motion } from "framer-motion";
import { Download, RefreshCw, Lock } from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from "recharts";
import { useAppStore } from "@/store/useAppStore";
import { getMetrics, exportUrl } from "@/api/client";

const PALETTE = ["#7B5EA7", "#9B7DC8", "#3D7A5F", "#9C7020", "#A03030", "#B0A499"];

const TIP = {
  contentStyle: {
    background: "#fff",
    border: "1px solid rgba(60,40,20,0.10)",
    borderRadius: 10,
    color: "#2C2622",
    fontSize: 12,
  },
};

function Kpi({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="card p-5 space-y-1">
      <p className="text-xs text-p-text-muted font-medium">{label}</p>
      <p className="text-3xl font-bold text-p-text tracking-tight">{value}</p>
      {sub && <p className="text-xs text-p-text-faint">{sub}</p>}
    </div>
  );
}

export default function Step3Dashboard() {
  const items        = useAppStore((s) => s.items);
  const uploadResult = useAppStore((s) => s.uploadResult);
  const metrics      = useAppStore((s) => s.metrics);
  const setMetrics   = useAppStore((s) => s.setMetrics);
  const activeRound  = useAppStore((s) => s.activeRound);
  const setStep      = useAppStore((s) => s.setStep);

  const roundId = uploadResult?.round_id ?? activeRound?.id;

  /* Live metric refresh */
  const refresh = () => {
    if (!roundId) return;
    getMetrics(roundId).then(setMetrics).catch(() => {});
  };

  useEffect(() => { refresh(); }, [roundId]); // eslint-disable-line react-hooks/exhaustive-deps

  const pendingCount = items.filter((i) => i.status === "requires_human").length;
  const queueDone    = pendingCount === 0;

  const derived = useMemo(() => {
    if (!metrics) return null;
    const autoPct = metrics.total > 0
      ? Math.round((metrics.auto_approved / metrics.total) * 100)
      : 0;
    const statusData = [
      { name: "Auto-aprobadas",  value: metrics.auto_approved },
      { name: "Resueltas manual",value: metrics.manual_resolved },
      { name: "Pendientes",      value: Math.max(0, metrics.requires_human - metrics.manual_resolved) },
      { name: "Genéricas",       value: metrics.generic },
    ].filter((d) => d.value > 0);

    const topBrands = (metrics.top_brands ?? []).slice(0, 12).map((b) => ({
      name: b.brand.length > 18 ? b.brand.slice(0, 18) + "…" : b.brand,
      count: b.count,
    }));

    return { autoPct, statusData, topBrands };
  }, [metrics]);

  if (items.length === 0 && !metrics) {
    return (
      <div className="text-center py-20 space-y-4">
        <p className="text-p-text-muted text-sm">Sin datos. Sube un archivo primero.</p>
        <button onClick={() => setStep(1)} className="btn-ghost text-sm">← Inicio</button>
      </div>
    );
  }

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-p-text tracking-tight">Dashboard</h1>
          <p className="text-sm text-p-text-muted">
            Paso 3{activeRound ? ` · ${activeRound.name}` : ""} · Métricas y exportación
          </p>
        </div>
        <div className="flex gap-2 items-center">
          <button onClick={refresh} className="btn-ghost text-xs" title="Refrescar">
            <RefreshCw className="w-3.5 h-3.5" />
          </button>

          {/* CL5: export button — solo activo cuando queue = 0 */}
          {queueDone && roundId ? (
            <a
              href={exportUrl(roundId)}
              download={`clasificacion_ronda_${roundId}.csv`}
              className="btn-primary text-sm"
            >
              <Download className="w-4 h-4" /> Exportar CSV
            </a>
          ) : (
            <button
              disabled
              title={`Aún hay ${pendingCount} respuestas pendientes de revisión`}
              className="btn-ghost text-sm text-p-text-faint cursor-not-allowed flex items-center gap-2"
            >
              <Lock className="w-3.5 h-3.5" />
              Exportar ({pendingCount} pendientes)
            </button>
          )}
        </div>
      </div>

      {/* KPIs */}
      {metrics ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Kpi label="Total"           value={metrics.total} />
          <Kpi label="Auto-aprobadas"  value={metrics.auto_approved} sub={`${derived?.autoPct ?? 0}% del total`} />
          <Kpi label="Resueltas manual"value={metrics.manual_resolved} />
          <Kpi label="Pendientes"      value={pendingCount} />
        </div>
      ) : (
        <div className="grid grid-cols-4 gap-3">
          {[0, 1, 2, 3].map((i) => <div key={i} className="card p-5 h-24 skeleton" />)}
        </div>
      )}

      {/* Charts */}
      {derived && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="card p-5 space-y-3">
            <h3 className="text-sm font-semibold text-p-text">Top marcas</h3>
            {derived.topBrands.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={derived.topBrands} layout="vertical" margin={{ left: 0, right: 16 }}>
                  <XAxis type="number" tick={{ fill: "#7A6F68", fontSize: 10 }} />
                  <YAxis type="category" dataKey="name" width={120} tick={{ fill: "#7A6F68", fontSize: 10 }} />
                  <Tooltip {...TIP} />
                  <Bar dataKey="count" fill="#7B5EA7" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-xs text-p-text-faint py-10 text-center">Sin datos aún</p>
            )}
          </div>

          <div className="card p-5 space-y-3">
            <h3 className="text-sm font-semibold text-p-text">Estado de clasificación</h3>
            {derived.statusData.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie data={derived.statusData} dataKey="value" nameKey="name"
                    cx="50%" cy="45%" outerRadius={80} paddingAngle={2}>
                    {derived.statusData.map((_, i) => (
                      <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                    ))}
                  </Pie>
                  <Legend iconType="circle" iconSize={8}
                    formatter={(v) => <span style={{ color: "#7A6F68", fontSize: 11 }}>{v}</span>} />
                  <Tooltip {...TIP} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex items-center justify-center h-[240px]">
                <p className="text-xs text-p-text-faint text-center">
                  Revisa entidades en el{" "}
                  <button onClick={() => setStep(2)} className="text-p-accent underline">Paso 2</button>
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Queue status bar */}
      {!queueDone && (
        <div className="card-subtle px-4 py-3 flex items-center justify-between text-sm">
          <span className="text-p-text-muted">
            <span className="font-semibold text-p-warning">{pendingCount}</span> respuestas pendientes — exportación bloqueada
          </span>
          <button onClick={() => setStep(2)} className="btn-ghost text-xs">
            Continuar revisión →
          </button>
        </div>
      )}
    </motion.div>
  );
}
