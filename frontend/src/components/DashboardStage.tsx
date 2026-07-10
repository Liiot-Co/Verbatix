import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Download, RefreshCw, RotateCcw } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";
import { useWizardStore } from "@/store/useWizardStore";
import { getMetrics, exportUrl } from "@/api/client";

const PALETTE = [
  "#7B5EA7",
  "#9B7DC8",
  "#3D7A5F",
  "#9C7020",
  "#A03030",
  "#B0A499",
];

const TIP = {
  contentStyle: {
    background: "#fff",
    border: "1px solid rgba(60,40,20,0.10)",
    borderRadius: 10,
    color: "#2C2622",
    fontSize: 12,
  },
};

function Kpi({
  label,
  value,
  sub,
}: {
  label: string;
  value: number | string;
  sub?: string;
}) {
  return (
    <div className="card p-5 space-y-1">
      <p className="text-xs text-p-text-muted font-medium">{label}</p>
      <p className="text-3xl font-bold text-p-text tracking-tight">{value}</p>
      {sub && <p className="text-xs text-p-text-faint">{sub}</p>}
    </div>
  );
}

interface Props {
  onReset: () => void;
}

export default function DashboardStage({ onReset }: Props) {
  const files      = useWizardStore((s) => s.files);
  const updateFile = useWizardStore((s) => s.updateFile);

  const doneFiles = files.filter(
    (f) => f.status === "done" && f.roundId !== null
  );

  const [selectedId, setSelectedId] = useState<string | null>(
    doneFiles[0]?.id ?? null
  );

  const selectedEntry =
    doneFiles.find((f) => f.id === selectedId) ?? doneFiles[0];

  const refresh = () => {
    if (!selectedEntry?.roundId) return;
    getMetrics(selectedEntry.roundId)
      .then((m) => updateFile(selectedEntry.id, { metrics: m }))
      .catch(() => {});
  };

  // Auto-load metrics when switching tabs
  useEffect(() => {
    if (selectedEntry?.roundId && !selectedEntry.metrics) {
      refresh();
    }
  }, [selectedEntry?.id]);

  // Auto-select first file when doneFiles populates
  useEffect(() => {
    if (!selectedId && doneFiles.length > 0) {
      setSelectedId(doneFiles[0]!.id);
    }
  }, [doneFiles.length]);

  const metrics = selectedEntry?.metrics ?? null;

  const derived = useMemo(() => {
    if (!metrics) return null;
    const autoPct =
      metrics.total > 0
        ? Math.round((metrics.auto_approved / metrics.total) * 100)
        : 0;
    const statusData = [
      { name: "Auto-aprobadas", value: metrics.auto_approved },
      { name: "Resueltas manual", value: metrics.manual_resolved },
      { name: "Genéricas", value: metrics.generic },
    ].filter((d) => d.value > 0);

    const topBrands = (metrics.top_brands ?? []).slice(0, 12).map((b) => ({
      name: b.brand.length > 18 ? b.brand.slice(0, 18) + "…" : b.brand,
      count: b.count,
    }));

    return { autoPct, statusData, topBrands };
  }, [metrics]);

  if (doneFiles.length === 0) {
    return (
      <div className="text-center py-20">
        <p className="text-p-text-muted text-sm">Sin datos procesados.</p>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="max-w-4xl mx-auto space-y-6"
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-p-text tracking-tight">
            Dashboard
          </h1>
          <p className="text-sm text-p-text-muted">
            {doneFiles.length}{" "}
            {doneFiles.length === 1 ? "ronda clasificada" : "rondas clasificadas"}
          </p>
        </div>
        <div className="flex gap-2 items-center">
          <button
            onClick={onReset}
            className="btn-ghost text-sm flex items-center gap-1.5"
            title="Comenzar nueva clasificación"
          >
            <RotateCcw className="w-3.5 h-3.5" /> Nueva
          </button>
          <button
            onClick={refresh}
            className="btn-ghost text-xs"
            title="Refrescar métricas"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
          {selectedEntry?.roundId && (
            <a
              href={exportUrl(selectedEntry.roundId)}
              download={`clasificacion_${selectedEntry.name}.xlsx`}
              className="btn-primary text-sm"
            >
              <Download className="w-4 h-4" /> Exportar XLSX
            </a>
          )}
        </div>
      </div>

      {/* Round tabs (only shown when >1 file) */}
      {doneFiles.length > 1 && (
        <div className="flex gap-2 flex-wrap">
          {doneFiles.map((f) => (
            <button
              key={f.id}
              onClick={() => setSelectedId(f.id)}
              className={[
                "px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                f.id === selectedId
                  ? "bg-p-accent text-white shadow-sm"
                  : "text-p-text-muted hover:text-p-text hover:bg-p-bg-subtle",
              ].join(" ")}
            >
              {f.name}
              {f.uploadResult && (
                <span className="ml-1.5 opacity-60">{f.uploadResult.total}</span>
              )}
            </button>
          ))}
        </div>
      )}

      {/* KPI cards */}
      {metrics ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Kpi label="Total" value={metrics.total} />
          <Kpi
            label="Auto-aprobadas"
            value={metrics.auto_approved}
            sub={`${derived?.autoPct ?? 0}% del total`}
          />
          <Kpi label="Resueltas manual" value={metrics.manual_resolved} />
          <Kpi label="Genéricas" value={metrics.generic} />
        </div>
      ) : (
        <div className="grid grid-cols-4 gap-3">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="card p-5 h-24 skeleton" />
          ))}
        </div>
      )}

      {/* Charts */}
      {derived && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="card p-5 space-y-3">
            <h3 className="text-sm font-semibold text-p-text">Top marcas</h3>
            {derived.topBrands.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart
                  data={derived.topBrands}
                  layout="vertical"
                  margin={{ left: 0, right: 16 }}
                >
                  <XAxis
                    type="number"
                    tick={{ fill: "#7A6F68", fontSize: 10 }}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={120}
                    tick={{ fill: "#7A6F68", fontSize: 10 }}
                  />
                  <Tooltip {...TIP} />
                  <Bar dataKey="count" fill="#7B5EA7" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-xs text-p-text-faint py-10 text-center">
                Sin datos aún
              </p>
            )}
          </div>

          <div className="card p-5 space-y-3">
            <h3 className="text-sm font-semibold text-p-text">
              Estado de clasificación
            </h3>
            {derived.statusData.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie
                    data={derived.statusData}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="45%"
                    outerRadius={80}
                    paddingAngle={2}
                  >
                    {derived.statusData.map((_, i) => (
                      <Cell
                        key={i}
                        fill={PALETTE[i % PALETTE.length]}
                      />
                    ))}
                  </Pie>
                  <Legend
                    iconType="circle"
                    iconSize={8}
                    formatter={(v) => (
                      <span style={{ color: "#7A6F68", fontSize: 11 }}>
                        {v}
                      </span>
                    )}
                  />
                  <Tooltip {...TIP} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-xs text-p-text-faint py-10 text-center">
                Sin datos aún
              </p>
            )}
          </div>
        </div>
      )}
    </motion.div>
  );
}
