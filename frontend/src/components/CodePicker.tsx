import { useEffect, useMemo, useState } from "react";
import { Plus, Check } from "lucide-react";
import { useWizardStore } from "@/store/useWizardStore";
import { getCodes, createCode, setResponseCodes } from "@/api/client";
import type { SurveyItem } from "@/api/types";

interface Props {
  item: SurveyItem;
  fileId: string;
  onSaved: () => void;
}

export default function CodePicker({ item, fileId, onSaved }: Props) {
  const activeStudyId    = useWizardStore((s) => s.activeStudyId);
  const codebook          = useWizardStore((s) => s.codebook);
  const codebookStudyId   = useWizardStore((s) => s.codebookStudyId);
  const setCodebook       = useWizardStore((s) => s.setCodebook);
  const resolveItemsForFile = useWizardStore((s) => s.resolveItemsForFile);
  const recordResolution   = useWizardStore((s) => s.recordResolution);
  const showToast         = useWizardStore((s) => s.showToast);

  const [selected, setSelected] = useState<Set<number>>(
    new Set((item.codes ?? []).map((c) => c.code_id))
  );
  const [search, setSearch] = useState("");
  const [newCodeName, setNewCodeName] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setSelected(new Set((item.codes ?? []).map((c) => c.code_id)));
  }, [item.id]);

  useEffect(() => {
    if (!activeStudyId || codebookStudyId === activeStudyId) return;
    getCodes(activeStudyId).then((codes) => setCodebook(activeStudyId, codes)).catch(() => {});
  }, [activeStudyId, codebookStudyId, setCodebook]);

  const suggested = item.codes ?? [];

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return codebook;
    return codebook.filter((c) => c.name.toLowerCase().includes(q));
  }, [codebook, search]);

  const grouped = useMemo(() => {
    const nets = new Map<string, typeof codebook>();
    for (const c of filtered) {
      const key = c.net?.name ?? "Sin neto";
      if (!nets.has(key)) nets.set(key, []);
      nets.get(key)!.push(c);
    }
    return Array.from(nets.entries());
  }, [filtered]);

  // Toggling only updates local selection — persisting is an explicit
  // action (Enter / Guardar), since a PUT can flip the item's status
  // to manual_resolved and drop it out of the pending queue.
  const toggle = (codeId: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(codeId)) next.delete(codeId);
      else next.add(codeId);
      return next;
    });
  };

  const save = async () => {
    setSaving(true);
    try {
      const wasPending = item.status === "requires_human";
      const updated = await setResponseCodes(item.id, Array.from(selected));
      resolveItemsForFile(fileId, updated, []);
      if (wasPending && updated.status !== "requires_human") recordResolution();
      showToast("Códigos guardados", "success");
      onSaved();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Error al guardar códigos", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleCreateCode = async () => {
    if (!activeStudyId || !newCodeName.trim()) return;
    const code = await createCode(activeStudyId, newCodeName.trim());
    setCodebook(activeStudyId, [...codebook, code]);
    setNewCodeName("");
    toggle(code.id);
  };

  // Keys 1..9 toggle the first suggested codes; Enter saves the set and advances
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "Enter") {
        e.preventDefault();
        save();
        return;
      }
      const n = Number(e.key);
      if (n >= 1 && n <= 9 && suggested[n - 1]) {
        e.preventDefault();
        toggle(suggested[n - 1]!.code_id);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [suggested, selected]);

  if (!activeStudyId) return null;

  return (
    <div className="space-y-3">
      <div className="text-[10px] font-mono uppercase tracking-wider text-p-text-faint">
        Códigos {saving && "· guardando..."}
      </div>

      {suggested.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {suggested.map((c, idx) => (
            <button
              key={c.code_id}
              onClick={() => toggle(c.code_id)}
              className={[
                "text-xs px-2 py-1 rounded-full border flex items-center gap-1 transition-colors",
                selected.has(c.code_id)
                  ? "bg-p-accent-soft border-p-accent/40 text-p-accent"
                  : "bg-p-bg-subtle border-p-border text-p-text-muted",
              ].join(" ")}
            >
              {idx < 9 && <span className="font-mono opacity-60">{idx + 1}</span>}
              {c.name}
            </button>
          ))}
        </div>
      )}

      <input
        className="input text-xs py-1.5"
        placeholder="Buscar código..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      <div className="max-h-40 overflow-y-auto flex flex-col gap-2">
        {grouped.map(([netName, codes]) => (
          <div key={netName}>
            <div className="text-[10px] font-mono uppercase text-p-text-faint mb-1">{netName}</div>
            <div className="flex flex-wrap gap-1.5">
              {codes.map((c) => (
                <button
                  key={c.id}
                  onClick={() => toggle(c.id)}
                  className={[
                    "text-xs px-2 py-1 rounded-full border transition-colors",
                    selected.has(c.id)
                      ? "bg-p-accent-soft border-p-accent/40 text-p-accent"
                      : "bg-p-bg-subtle border-p-border text-p-text-muted",
                  ].join(" ")}
                >
                  {c.name}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="flex gap-2">
        <input
          className="input text-xs py-1.5 flex-1"
          placeholder="Crear código nuevo..."
          value={newCodeName}
          onChange={(e) => setNewCodeName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleCreateCode()}
        />
        <button className="btn-ghost text-xs px-2" onClick={handleCreateCode}>
          <Plus className="w-3.5 h-3.5" />
        </button>
      </div>

      <button className="btn-primary text-xs w-full justify-center" onClick={save} disabled={saving}>
        <Check className="w-3.5 h-3.5" />
        Guardar códigos
        <kbd className="font-mono text-[10px] opacity-70 ml-1">↵</kbd>
      </button>
    </div>
  );
}
