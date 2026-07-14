import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  BarChart3,
  CheckCircle2,
  ClipboardCheck,
  Download,
  FileSpreadsheet,
  Loader2,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { motion } from "framer-motion";
import { downloadCodebookExport, getStudio, getStudioReport } from "@/api/client";
import type { CodingType, ReportCodeStat, StudioReport, StudioStatus } from "@/api/types";
import { glowVariantForIndex } from "@/components/GlowCard";
import { studyDisplayName, studyKey } from "@/lib/projectTree";
import { useVerbatixStore } from "@/store/useVerbatixStore";
import Breadcrumb from "./Breadcrumb";

const AUDIT_BADGE: Record<
  StudioStatus["audit"]["status"],
  { label: string; className: string }
> = {
  not_started: { label: "Sin auditar", className: "badge-pending" },
  in_progress: { label: "Auditoría en curso", className: "badge-warning" },
  approved: { label: "Auditado", className: "badge-success" },
};

const BAR_PASTELS = [
  "linear-gradient(90deg, #C4B8E8, #E8E0F8)",
  "linear-gradient(90deg, #F0C8A8, #FCE8D8)",
  "linear-gradient(90deg, #B8D4F0, #DCEEF8)",
  "linear-gradient(90deg, #E8C4D8, #F4E0EC)",
  "linear-gradient(90deg, #C8E8D8, #E0F4E8)",
] as const;

function barPastel(index: number): string {
  return BAR_PASTELS[index % BAR_PASTELS.length]!;
}

function formatProcessedAt(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("es-CO", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  } catch {
    return "—";
  }
}

function formatCount(n: number): string {
  return n.toLocaleString("es-CO");
}

/** Pasteles del mockup: lavanda, melocotón, menta, cian, rosa, arena. */
const CLOUD_PASTELS = [
  "#9B8AD4",
  "#E8A07A",
  "#6BB89A",
  "#5DB8C8",
  "#E08AAD",
  "#C4A07A",
] as const;

function wordCloudStyle(freq: number, min: number, max: number, index: number) {
  const t = max > min ? (freq - min) / (max - min) : 1;
  const fontSize = Math.round(12 + t * 22);
  const fontWeight = t >= 0.55 ? 700 : 600;
  const color = CLOUD_PASTELS[index % CLOUD_PASTELS.length]!;
  return { fontSize, color, fontWeight };
}

type WordBBox = { x: number; y: number; w: number; h: number };

function boxesOverlap(a: WordBBox, b: WordBBox): boolean {
  return !(a.x + a.w < b.x || b.x + b.w < a.x || a.y + a.h < b.y || b.y + b.h < a.y);
}

let _measureCtx: CanvasRenderingContext2D | null = null;

function measureWord(label: string, fontSize: number, fontWeight: number): { w: number; h: number } {
  if (typeof document !== "undefined") {
    if (!_measureCtx) {
      _measureCtx = document.createElement("canvas").getContext("2d");
    }
    if (_measureCtx) {
      _measureCtx.font = `${fontWeight} ${fontSize}px "Open Sans", Satoshi, system-ui, sans-serif`;
      return {
        w: Math.ceil(_measureCtx.measureText(label).width),
        h: Math.ceil(fontSize * 1.2),
      };
    }
  }
  return { w: Math.ceil(label.length * fontSize * 0.56), h: Math.ceil(fontSize * 1.2) };
}

/**
 * Empaqueta en espiral ovalada: grandes al centro, chicas rellenan huecos.
 * Mide el texto real y deja un hueco corto sin solapes.
 */
function layoutCloud(
  words: CloudWord[],
  containerW: number,
  containerH: number,
): PlacedCloudWord[] {
  if (words.length === 0 || containerW < 40 || containerH < 40) return [];

  const sorted = [...words].sort((a, b) => b.fontSize - a.fontSize || b.frequency - a.frequency);
  const margin = 10;
  const gap = 8;
  const cx = containerW / 2;
  const cy = containerH / 2;
  const placed: PlacedCloudWord[] = [];
  const boxes: WordBBox[] = [];

  const tryPlace = (
    label: string,
    fontSize: number,
    fontWeight: number,
  ): { x: number; y: number; w: number; h: number; fontSize: number } | null => {
    const { w, h } = measureWord(label, fontSize, fontWeight);
    const boxW = w + gap;
    const boxH = h + gap * 0.7;
    const maxR = Math.max(containerW, containerH);

    for (let step = 0; step < 900; step++) {
      const angle = step * 0.35;
      const radius = step === 0 ? 0 : 4 + step * 0.55;
      if (radius > maxR) break;
      const x = cx + Math.cos(angle) * radius * 1.15 - boxW / 2;
      const y = cy + Math.sin(angle) * radius * 0.72 - boxH / 2;
      if (x < margin || y < margin || x + boxW > containerW - margin || y + boxH > containerH - margin) {
        continue;
      }
      const candidate: WordBBox = { x, y, w: boxW, h: boxH };
      if (!boxes.some((b) => boxesOverlap(candidate, b))) {
        return { x, y, w: boxW, h: boxH, fontSize };
      }
    }
    return null;
  };

  for (const word of sorted) {
    let spot =
      tryPlace(word.label, word.fontSize, word.fontWeight) ??
      tryPlace(word.label, Math.max(10, word.fontSize - 2), word.fontWeight) ??
      tryPlace(word.label, Math.max(10, word.fontSize - 4), word.fontWeight);

    if (!spot) {
      const fs = Math.max(10, word.fontSize - 4);
      const { w, h } = measureWord(word.label, fs, word.fontWeight);
      const boxW = w + gap;
      const boxH = h + gap * 0.7;
      spot = {
        x: Math.min(containerW - boxW - margin, Math.max(margin, cx - boxW / 2)),
        y: Math.min(containerH - boxH - margin, Math.max(margin, cy - boxH / 2)),
        w: boxW,
        h: boxH,
        fontSize: fs,
      };
    }

    boxes.push({ x: spot.x, y: spot.y, w: spot.w, h: spot.h });
    placed.push({
      ...word,
      fontSize: spot.fontSize,
      left: ((spot.x + spot.w / 2) / containerW) * 100,
      top: ((spot.y + spot.h / 2) / containerH) * 100,
    });
  }

  if (placed.length === 0) return placed;
  const xs = boxes.map((b) => b.x + b.w / 2);
  const ys = boxes.map((b) => b.y + b.h / 2);
  const midX = (Math.min(...xs) + Math.max(...xs)) / 2;
  const midY = (Math.min(...ys) + Math.max(...ys)) / 2;
  const dx = ((cx - midX) / containerW) * 100;
  const dy = ((cy - midY) / containerH) * 100;
  if (Math.abs(dx) <= 1 && Math.abs(dy) <= 1) return placed;
  return placed.map((p) => ({
    ...p,
    left: Math.min(92, Math.max(8, p.left + dx)),
    top: Math.min(90, Math.max(10, p.top + dy)),
  }));
}

const HOVER_GLOW_CLASS: Record<1 | 2 | 3, string> = {
  1: "glow-card-hover-1",
  2: "glow-card-hover-2",
  3: "glow-card-hover-3",
};

const GLOW_CLASS: Record<1 | 2 | 3, string> = {
  1: "glow-card-1",
  2: "glow-card-2",
  3: "glow-card-3",
};

export default function ReportView() {
  const { studioId } = useParams<{ studioId: string }>();
  const navigate = useNavigate();
  const showToast = useVerbatixStore((s) => s.showToast);

  const [studio, setStudio] = useState<StudioStatus | null>(null);
  const [report, setReport] = useState<StudioReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    if (!studioId) return;
    setLoading(true);
    Promise.all([getStudio(studioId), getStudioReport(studioId)])
      .then(([s, r]) => {
        setStudio(s);
        setReport(r);
      })
      .catch(() => showToast("No se pudo cargar el reporte.", "error"))
      .finally(() => setLoading(false));
  }, [studioId, showToast]);

  const codingType: CodingType = studio?.coding_type ?? "brands";
  const typeLabel = codingType === "brands" ? "marcas" : "razones";
  const topCodes = useMemo(() => (report?.codes ?? []).slice(0, 5), [report?.codes]);

  const cloudCodes = useMemo(() => {
    const codes = [...(report?.codes ?? [])]
      .sort((a, b) => b.frequency - a.frequency)
      .slice(0, 22);
    if (codes.length === 0) return [];
    const freqs = codes.map((c) => c.frequency);
    const min = Math.min(...freqs);
    const max = Math.max(...freqs);
    return codes.map((c, index) => {
      const style = wordCloudStyle(c.frequency, min, max, index);
      return { ...c, ...style };
    });
  }, [report?.codes]);

  const handleExport = useCallback(async () => {
    if (!studioId || exporting) return;
    setExporting(true);
    try {
      await downloadCodebookExport(studioId);
      showToast("Paquete descargado (Excel + MDD).", "success");
    } catch {
      showToast("No se pudo exportar el paquete.", "error");
    } finally {
      setExporting(false);
    }
  }, [studioId, exporting, showToast]);

  const studyCrumb = studio
    ? {
        label: studyDisplayName(studio.name, studio.coding_type),
        to: `/projects/${studio.project_id}/studies/${studyKey(studio.coding_type, studio.name)}`,
      }
    : { label: "Estudio", to: `/studios/${studioId}` };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24 text-p-text-muted gap-2">
        <Loader2 className="w-5 h-5 animate-spin" />
        Cargando reporte...
      </div>
    );
  }

  const studyTitle = studio
    ? studyDisplayName(studio.name, studio.coding_type)
    : "Reporte del estudio";

  return (
    <div className="space-y-5 max-w-6xl">
      <Breadcrumb
        items={[
          { label: "Proyectos", to: "/" },
          ...(studio ? [{ label: studio.project_name, to: `/projects/${studio.project_id}` }] : []),
          studyCrumb,
          { label: "Reporte" },
        ]}
      />

      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div className="space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="font-heading text-2xl sm:text-3xl font-semibold text-p-text tracking-tight">
              {studyTitle}
            </h1>
            <span className="text-[10px] font-semibold tracking-[0.08em] uppercase px-2.5 py-1 rounded-full border border-p-border bg-p-surface text-p-text-muted">
              R{studio?.round_number ?? "—"}
            </span>
          </div>
          <p className="text-sm text-p-text-muted">
            Resultado final · procesado el{" "}
            <span className="text-p-text font-medium">
              {formatProcessedAt(report?.processed_at ?? null)}
            </span>
          </p>
        </div>

        <div className="glow-card glow-card-2 p-3 flex items-center gap-3 shrink-0 self-start">
          <ClipboardCheck className="w-4 h-4 text-p-accent shrink-0" />
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-p-text-faint">
              Auditoría
            </p>
            <span className={AUDIT_BADGE[studio?.audit.status ?? "not_started"].className}>
              {AUDIT_BADGE[studio?.audit.status ?? "not_started"].label}
            </span>
          </div>
          {studio?.audit.status === "approved" ? (
            <CheckCircle2 className="w-5 h-5 text-p-success shrink-0" />
          ) : (
            <button
              type="button"
              className="btn-ghost-sm shrink-0"
              onClick={() => navigate(`/studios/${studioId}/audit`)}
            >
              Auditar
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        <GlowStatCard
          variant={glowVariantForIndex(0)}
          icon={<TrendingUp className="w-4 h-4" />}
          label="Total registros"
          value={formatCount(report?.verbatims_total ?? 0)}
          hint="Respuestas procesadas"
        />
        <GlowStatCard
          variant={glowVariantForIndex(1)}
          icon={<Sparkles className="w-4 h-4" />}
          label="NLP automático"
          value={`${report?.auto_coded_pct ?? 0}%`}
          hint={`${formatCount(report?.auto_coded ?? 0)} sin intervención`}
          valueClass="text-p-success"
        />
        <GlowStatCard
          variant={glowVariantForIndex(2)}
          icon={<ClipboardCheck className="w-4 h-4" />}
          label="Revisión manual"
          value={`${report?.manually_coded_pct ?? 0}%`}
          hint={`${formatCount(report?.manually_coded ?? 0)} validadas manualmente`}
          valueClass="text-p-warning"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <section className={`glow-card-hover ${HOVER_GLOW_CLASS[glowVariantForIndex(0)]} p-5 space-y-3 transition-transform hover:-translate-y-0.5`}>
          <SectionHeader
            icon={<BarChart3 className="w-4 h-4 text-p-accent" />}
            title={`Top 5 ${typeLabel}`}
            subtitle="Distribución de menciones"
          />
          {topCodes.length === 0 ? (
            <p className="text-sm text-p-text-faint py-6 text-center">Sin códigos con frecuencia.</p>
          ) : (
            <div className="space-y-2.5">
              {topCodes.map((code, index) => (
                <TopBar
                  key={code.id}
                  code={code}
                  rank={index + 1}
                  maxPct={topCodes[0]?.pct ?? 1}
                  gradient={barPastel(index)}
                />
              ))}
            </div>
          )}
        </section>

        <section className={`glow-card-hover ${HOVER_GLOW_CLASS[glowVariantForIndex(1)]} p-5 space-y-4 transition-transform hover:-translate-y-0.5`}>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-p-text-faint">
              Nube de respuestas
            </p>
            <h2 className="text-base font-bold text-p-text mt-0.5">Mapa semántico</h2>
          </div>
          {cloudCodes.length === 0 ? (
            <p className="text-sm text-p-text-faint py-6 text-center">Sin datos para la nube.</p>
          ) : (
            <WordCloud codes={cloudCodes} />
          )}
        </section>
      </div>

      <div className={`glow-card-hover ${HOVER_GLOW_CLASS[glowVariantForIndex(2)]} p-5 sm:p-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 transition-transform hover:-translate-y-0.5`}>
        <div className="flex items-start gap-4">
          <div className="w-11 h-11 rounded-xl bg-p-text flex items-center justify-center shrink-0 shadow-sm">
            <FileSpreadsheet className="w-5 h-5 text-white" />
          </div>
          <div className="space-y-1">
            <p className="text-sm font-bold uppercase tracking-wide text-p-text">
              Libro de Códigos listo
            </p>
            <p className="text-xs text-p-text-muted leading-relaxed max-w-lg">
              Incluye Excel del Libro de Códigos y 2 archivos MDD (.txt).{" "}
              {formatCount(report?.verbatims_total ?? 0)} registros ·{" "}
              {report?.codes.length ?? 0} {typeLabel}
            </p>
          </div>
        </div>
        <button
          type="button"
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white bg-p-text hover:bg-p-text/90 transition-colors shrink-0 disabled:opacity-50"
          disabled={exporting}
          onClick={() => void handleExport()}
        >
          {exporting ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Download className="w-4 h-4" />
          )}
          Exportar ZIP
        </button>
      </div>
    </div>
  );
}

function SectionHeader({
  icon,
  title,
  subtitle,
}: {
  icon: ReactNode;
  title: string;
  subtitle: string;
}) {
  return (
    <div className="flex items-start gap-2.5">
      <div className="mt-0.5">{icon}</div>
      <div>
        <h2 className="text-sm font-bold uppercase tracking-wide text-p-text">{title}</h2>
        <p className="text-[11px] text-p-text-faint font-subtitle">{subtitle}</p>
      </div>
    </div>
  );
}

function GlowStatCard({
  variant,
  icon,
  label,
  value,
  hint,
  valueClass = "text-p-text",
}: {
  variant: 1 | 2 | 3;
  icon: ReactNode;
  label: string;
  value: string | number;
  hint: string;
  valueClass?: string;
}) {
  return (
    <div className={`glow-card ${GLOW_CLASS[variant]} p-5 space-y-2 card-hover-lift`}>
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-p-text-muted">
          {label}
        </p>
        <span className="text-p-text-faint">{icon}</span>
      </div>
      <p className={`text-3xl font-bold tracking-tight ${valueClass}`}>{value}</p>
      <p className="text-[11px] text-p-text-faint font-subtitle">{hint}</p>
    </div>
  );
}

function TopBar({
  code,
  rank,
  maxPct,
  gradient,
}: {
  code: ReportCodeStat;
  rank: number;
  maxPct: number;
  gradient: string;
}) {
  const widthPct = maxPct > 0 ? (code.pct / maxPct) * 100 : 0;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2 text-xs">
        <span className="w-5 h-5 rounded-md bg-p-bg-subtle text-[10px] font-bold text-p-text-faint flex items-center justify-center shrink-0">
          {rank}
        </span>
        <span className="font-semibold text-p-text truncate flex-1">{code.label}</span>
        <span className="text-p-text-muted font-medium tabular-nums shrink-0">
          {(code.pct * 100).toFixed(1)}%
        </span>
      </div>
      <div className="h-2.5 rounded-full bg-[#f4f2fa] overflow-hidden ml-7">
        <motion.div
          className="h-full rounded-full"
          style={{ background: gradient }}
          initial={{ width: 0 }}
          animate={{ width: `${widthPct}%` }}
          transition={{ duration: 0.5, ease: [0.19, 1, 0.22, 1] as const, delay: rank * 0.05 }}
        />
      </div>
    </div>
  );
}

type CloudWord = ReportCodeStat & {
  fontSize: number;
  color: string;
  fontWeight: number;
};

type PlacedCloudWord = CloudWord & { left: number; top: number };

function WordCloud({ codes }: { codes: CloudWord[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => {
      const rect = el.getBoundingClientRect();
      setSize({ w: Math.floor(rect.width), h: Math.floor(rect.height) });
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const placed = useMemo(
    () => (size.w > 0 ? layoutCloud(codes, size.w, size.h) : []),
    [codes, size],
  );

  return (
    <div
      ref={containerRef}
      className="relative rounded-xl bg-[#f7f6f9] h-[280px] overflow-hidden"
    >
      {placed.map((code, index) => (
        <div
          key={code.id}
          className="absolute -translate-x-1/2 -translate-y-1/2"
          style={{ left: `${code.left}%`, top: `${code.top}%` }}
        >
          <motion.span
            initial={{ opacity: 0, scale: 0.92 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{
              duration: 0.3,
              delay: index * 0.02,
              ease: [0.19, 1, 0.22, 1] as const,
            }}
            whileHover={{ scale: 1.1, y: -1 }}
            className="block cursor-default select-none tracking-tight whitespace-nowrap"
            style={{
              fontSize: `${code.fontSize}px`,
              color: code.color,
              fontWeight: code.fontWeight,
              fontFamily: '"Open Sans", Satoshi, system-ui, sans-serif',
              lineHeight: 1.1,
            }}
            title={`${code.frequency} menciones (${(code.pct * 100).toFixed(1)}%)`}
          >
            {code.label}
          </motion.span>
        </div>
      ))}
    </div>
  );
}
