import type { SessionStats } from "@/store/useWizardStore";

function formatElapsed(ms: number): string {
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

export default function SessionSummary({ session }: { session: SessionStats }) {
  const elapsed = session.startedAt ? Date.now() - session.startedAt : 0;

  const stats = [
    { label: "Resueltos", value: session.resolvedCount },
    { label: "Cascadas", value: session.cascadeCount },
    { label: "Tiempo", value: formatElapsed(elapsed) },
    { label: "Racha máxima", value: session.maxStreak },
  ];

  return (
    <div className="grid grid-cols-4 gap-2 pt-2">
      {stats.map((s) => (
        <div key={s.label} className="text-center">
          <div className="text-lg font-bold text-p-text">{s.value}</div>
          <div className="text-[10px] font-mono uppercase tracking-wider text-p-text-faint">
            {s.label}
          </div>
        </div>
      ))}
    </div>
  );
}
