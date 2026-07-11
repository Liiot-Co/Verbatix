import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { useWizardStore } from "@/store/useWizardStore";
import { getCodes, getNets, createCode, createNet } from "@/api/client";
import type { Code, Net } from "@/api/types";

export default function CodebookView() {
  const activeStudyId = useWizardStore((s) => s.activeStudyId);
  const [codes, setCodes] = useState<Code[]>([]);
  const [nets, setNets] = useState<Net[]>([]);
  const [newCodeName, setNewCodeName] = useState("");
  const [newNetId, setNewNetId] = useState<number | "">("");
  const [newNetName, setNewNetName] = useState("");

  const reload = () => {
    if (!activeStudyId) return;
    getCodes(activeStudyId).then(setCodes).catch(() => {});
    getNets(activeStudyId).then(setNets).catch(() => {});
  };

  useEffect(reload, [activeStudyId]);

  if (!activeStudyId) {
    return (
      <div className="flex-1 flex items-center justify-center text-p-text-muted text-sm">
        Elegí o creá un estudio para ver su libro de códigos.
      </div>
    );
  }

  const grouped = nets.map((net) => ({
    net,
    codes: codes.filter((c) => c.net?.id === net.id),
  }));
  const unassigned = codes.filter((c) => !c.net);

  const handleAddNet = async () => {
    if (!newNetName.trim()) return;
    await createNet(activeStudyId, newNetName.trim());
    setNewNetName("");
    reload();
  };

  const handleAddCode = async () => {
    if (!newCodeName.trim()) return;
    await createCode(activeStudyId, newCodeName.trim(), newNetId === "" ? null : newNetId);
    setNewCodeName("");
    reload();
  };

  return (
    <div className="flex-1 overflow-y-auto px-8 py-7">
      <div className="mb-6">
        <div className="font-subtitle text-[11px] tracking-[0.18em] uppercase text-p-text-faint mb-1.5">
          Libro de códigos
        </div>
        <h2 className="font-heading font-extrabold text-2xl tracking-tight text-p-text">
          Netos y códigos del estudio activo
        </h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <div className="card p-4 flex flex-col gap-2">
          <div className="font-subtitle text-[10.5px] tracking-wider uppercase text-p-text-faint">Nuevo neto</div>
          <div className="flex gap-2">
            <input className="input text-sm" placeholder="Nombre del neto" value={newNetName}
              onChange={(e) => setNewNetName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAddNet()} />
            <button className="btn-primary text-xs px-3" onClick={handleAddNet}><Plus className="w-3.5 h-3.5" /></button>
          </div>
        </div>
        <div className="card p-4 flex flex-col gap-2">
          <div className="font-subtitle text-[10.5px] tracking-wider uppercase text-p-text-faint">Nuevo código</div>
          <div className="flex gap-2">
            <select className="input text-sm w-32" value={newNetId} onChange={(e) => setNewNetId(e.target.value === "" ? "" : Number(e.target.value))}>
              <option value="">Sin neto</option>
              {nets.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
            </select>
            <input className="input text-sm flex-1" placeholder="Nombre del código" value={newCodeName}
              onChange={(e) => setNewCodeName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAddCode()} />
            <button className="btn-primary text-xs px-3" onClick={handleAddCode}><Plus className="w-3.5 h-3.5" /></button>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-4">
        {grouped.map(({ net, codes: netCodes }) => (
          <div key={net.id} className="card p-4">
            <div className="font-semibold text-sm text-p-text mb-2">{net.name}</div>
            {netCodes.length === 0 ? (
              <div className="text-xs text-p-text-faint">Sin códigos todavía.</div>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {netCodes.map((c) => (
                  <span key={c.id} className="text-xs px-2 py-1 rounded-full bg-p-bg-subtle border border-p-border text-p-text">
                    {c.name}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
        {unassigned.length > 0 && (
          <div className="card p-4">
            <div className="font-semibold text-sm text-p-text mb-2">Sin neto</div>
            <div className="flex flex-wrap gap-1.5">
              {unassigned.map((c) => (
                <span key={c.id} className="text-xs px-2 py-1 rounded-full bg-p-bg-subtle border border-p-border text-p-text">
                  {c.name}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
