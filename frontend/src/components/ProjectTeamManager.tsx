import { useEffect, useRef, useState } from "react";
import { Plus, Trash2, Users, X } from "lucide-react";
import { assignProjectMember, getAdminUsers, getProjectMembers, revokeProjectMember } from "@/api/client";
import type { AdminUser, ProjectMember } from "@/api/types";
import RoleBadge from "@/components/RoleBadge";

export default function ProjectTeamManager({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false);
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const closeRef = useRef<HTMLButtonElement>(null);
  const load = () => void Promise.all([getProjectMembers(projectId), getAdminUsers("active")]).then(([nextMembers, nextUsers]) => { setMembers(nextMembers); setUsers(nextUsers); });
  useEffect(() => {
    if (!open) return;
    load(); requestAnimationFrame(() => closeRef.current?.focus());
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey);
  }, [open, projectId]);
  const assignedIds = new Set(members.map((member) => member.user_id));
  return <><button onClick={() => setOpen(true)} className="btn-ghost text-xs"><Users className="w-3.5 h-3.5" />Gestionar equipo</button>{open && <div className="fixed inset-0 z-50 bg-black/20 grid place-items-end sm:place-items-center" role="dialog" aria-modal="true" aria-label="Gestionar equipo" onMouseDown={() => setOpen(false)}><div className="card w-full sm:max-w-lg max-h-[85vh] overflow-auto p-5 rounded-b-none sm:rounded-2xl" onMouseDown={(event) => event.stopPropagation()}><div className="flex justify-between items-center"><div><h2 className="font-heading font-semibold text-p-text">Gestionar equipo</h2><p className="text-xs text-p-text-muted mt-1">Añade o retira acceso a este proyecto.</p></div><button ref={closeRef} onClick={() => setOpen(false)} className="btn-ghost p-2" aria-label="Cerrar"><X className="w-4 h-4" /></button></div><div className="flex gap-2 mt-5"><select className="input text-sm flex-1" value={selectedId} onChange={(event) => setSelectedId(event.target.value)}><option value="">Seleccionar usuario activo…</option>{users.filter((user) => !assignedIds.has(user.id) && user.roles.length > 0).map((user) => <option value={user.id} key={user.id}>{user.name ?? user.email} · {user.roles.join(", ")}</option>)}</select><button disabled={!selectedId} className="btn-primary" onClick={async () => { await assignProjectMember(projectId, selectedId); setSelectedId(""); load(); }}><Plus className="w-4 h-4" />Añadir</button></div><div className="space-y-2 mt-5">{members.map((member) => <div key={member.user_id} className="card-subtle p-3 flex items-center gap-3"><div className="avatar w-8 h-8">{member.initials}</div><div className="flex-1 min-w-0"><div className="text-sm font-medium text-p-text truncate">{member.name ?? member.email}</div><div className="flex gap-1 mt-1">{member.roles.map((role) => <RoleBadge key={role} role={role} />)}</div></div><button className="btn-ghost p-2 text-p-error" aria-label={`Retirar a ${member.name ?? member.email}`} onClick={async () => { if (confirm("¿Retirar el acceso de esta persona al proyecto?")) { await revokeProjectMember(projectId, member.user_id); load(); } }}><Trash2 className="w-4 h-4" /></button></div>)}{members.length === 0 && <p className="text-sm text-p-text-faint text-center py-5">Todavía no hay personas asignadas.</p>}</div></div></div>}</>;
}
