import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { getProjectMembers } from "@/api/client";
import type { AssignedUserPreview, ProjectMember } from "@/api/types";
import RoleBadge from "@/components/RoleBadge";

export default function AvatarStack({ projectId, users, total }: { projectId: string; users: AssignedUserPreview[]; total: number }) {
  const [open, setOpen] = useState(false);
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    void getProjectMembers(projectId).then(setMembers);
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    requestAnimationFrame(() => closeRef.current?.focus());
    return () => window.removeEventListener("keydown", onKey);
  }, [open, projectId]);

  if (total === 0) return <span className="text-[11px] text-p-text-faint">Sin equipo</span>;
  return <>
    <div className="flex items-center -space-x-2" aria-label={`${total} personas asignadas`}>
      {users.slice(0, 3).map((person) => <div key={person.id} title={`${person.name ?? person.email} · ${person.roles.join(", ")}`} className="avatar w-7 h-7 text-[10px] border-2 border-p-surface">{person.initials}</div>)}
      {total > 3 && <button onClick={(event) => { event.preventDefault(); setOpen(true); }} className="avatar w-7 h-7 text-[10px] border-2 border-p-surface bg-p-bg-subtle text-p-text-muted">+{total - 3}</button>}
    </div>
    {open && <div className="fixed inset-0 z-50 grid place-items-end sm:place-items-center bg-black/20 p-0 sm:p-4" role="dialog" aria-modal="true" aria-label="Equipo asignado" onMouseDown={() => setOpen(false)}>
      <div className="card w-full sm:max-w-md max-h-[80vh] overflow-auto rounded-b-none sm:rounded-2xl p-5" onMouseDown={(event) => event.stopPropagation()}>
        <div className="flex items-center justify-between mb-4"><h2 className="font-heading font-semibold text-p-text">Equipo asignado</h2><button ref={closeRef} onClick={() => setOpen(false)} className="btn-ghost p-2" aria-label="Cerrar"><X className="w-4 h-4" /></button></div>
        <div className="space-y-2">{members.map((member) => <div key={member.user_id} className="card-subtle p-3 flex items-center gap-3"><div className="avatar w-8 h-8">{(member.name ?? member.email).charAt(0).toUpperCase()}</div><div className="min-w-0 flex-1"><div className="text-sm font-medium text-p-text truncate">{member.name ?? member.email}</div><div className="text-xs text-p-text-faint truncate">{member.email}</div></div><div className="flex gap-1 flex-wrap justify-end">{member.roles.map((role) => <RoleBadge key={role} role={role} />)}</div></div>)}</div>
      </div>
    </div>}
  </>;
}
