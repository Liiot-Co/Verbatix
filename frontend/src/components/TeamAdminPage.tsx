import { useEffect, useMemo, useState } from "react";
import { Search, ShieldCheck, UserRoundCheck } from "lucide-react";
import { approveAndAssign, getAdminUsers, getProjects, setUserStatus } from "@/api/client";
import type { AdminUser, ProjectListItem, RoleCode } from "@/api/types";
import RoleBadge from "@/components/RoleBadge";
import { useVerbatixStore } from "@/store/useVerbatixStore";

const ROLES: RoleCode[] = ["codificador", "supervisor", "admin"];

export default function TeamAdminPage() {
  const [tab, setTab] = useState<"pending" | "users" | "projects">("pending");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<AdminUser | null>(null);
  const [roles, setRoles] = useState<RoleCode[]>([]);
  const [projectIds, setProjectIds] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const showToast = useVerbatixStore((state) => state.showToast);
  const load = () => void Promise.all([getAdminUsers(), getProjects()]).then(([nextUsers, nextProjects]) => { setUsers(nextUsers); setProjects(nextProjects); });
  useEffect(load, []);
  const visible = useMemo(() => users.filter((user) => (tab !== "pending" || user.account_status === "pending") && `${user.name} ${user.email}`.toLowerCase().includes(query.toLowerCase())), [query, tab, users]);
  const openUser = (user: AdminUser) => {
    setSelected(user);
    setRoles(user.roles);
    setProjectIds(user.project_ids);
  };
  const saveUser = async () => {
    if (!selected || saving) return;
    setSaving(true);
    try {
      await approveAndAssign(selected.id, roles, projectIds);
      showToast("Roles y proyectos guardados.", "success");
      setSelected(null);
      load();
    } catch {
      showToast("No se pudieron guardar las asignaciones.", "error");
    } finally {
      setSaving(false);
    }
  };
  return <div className="max-w-5xl mx-auto py-4 space-y-5"><div><h1 className="font-heading text-xl font-semibold text-p-text">Equipo y asignaciones</h1><p className="text-sm text-p-text-muted mt-1">Aprueba cuentas y combina roles globales con visibilidad por proyecto.</p></div>
    <div className="flex gap-1 border-b border-p-border">{(["pending", "users", "projects"] as const).map((value) => <button key={value} onClick={() => setTab(value)} className={`px-4 py-2 text-sm ${tab === value ? "text-p-accent border-b-2 border-p-accent" : "text-p-text-muted"}`}>{value === "pending" ? "Pendientes" : value === "users" ? "Usuarios" : "Por proyecto"}</button>)}</div>
    <div className="relative"><Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-p-text-faint" /><input className="input pl-10" placeholder="Buscar personas…" value={query} onChange={(e) => setQuery(e.target.value)} /></div>
    {tab === "projects" ? <div className="grid sm:grid-cols-2 gap-3">{projects.map((project) => <div className="card-subtle p-4" key={project.id}><div className="font-medium text-p-text">{project.name}</div><div className="text-xs text-p-text-faint mt-1">{project.assigned_users_count} asignados</div></div>)}</div> : <div className="space-y-2">{visible.map((person) => <button onClick={() => openUser(person)} key={person.id} className="card-subtle p-4 w-full flex items-center gap-3 text-left"><div className="avatar w-9 h-9">{(person.name ?? person.email).charAt(0).toUpperCase()}</div><div className="flex-1 min-w-0"><div className="font-medium text-sm text-p-text truncate">{person.name ?? person.email}</div><div className="text-xs text-p-text-faint truncate">{person.email} · {person.assignments_count} {person.assignments_count === 1 ? "proyecto" : "proyectos"}</div></div><div className="hidden sm:flex gap-1">{person.roles.map((role) => <RoleBadge role={role} key={role} />)}</div><span className="chip text-[10px]">{person.account_status}</span></button>)}</div>}
    {selected && <div className="fixed inset-0 z-50 bg-black/20 grid place-items-end sm:place-items-center" onMouseDown={() => !saving && setSelected(null)}><div className="card w-full sm:max-w-lg p-6 rounded-b-none sm:rounded-2xl" onMouseDown={(event) => event.stopPropagation()}><h2 className="font-heading font-semibold text-p-text">{selected.name ?? selected.email}</h2><p className="text-xs text-p-text-muted mt-1">Selecciona roles y proyectos. La aprobación se guarda en una sola transacción.</p><div className="mt-5"><div className="form-label mb-2">Roles</div><div className="flex flex-wrap gap-2">{ROLES.map((role) => <label key={role} className="chip cursor-pointer"><input type="checkbox" checked={roles.includes(role)} onChange={() => setRoles((current) => current.includes(role) ? current.filter((item) => item !== role) : [...current, role])} />{role}</label>)}</div></div><div className="mt-5"><div className="form-label mb-2">Proyectos · {projectIds.length} seleccionados</div><div className="max-h-48 overflow-auto space-y-2">{projects.map((project) => <label key={project.id} className={`card-subtle p-3 flex gap-2 text-sm cursor-pointer ${projectIds.includes(project.id) ? "border-p-accent bg-p-accent/5" : ""}`}><input type="checkbox" checked={projectIds.includes(project.id)} onChange={() => setProjectIds((current) => current.includes(project.id) ? current.filter((id) => id !== project.id) : [...current, project.id])} />{project.name}</label>)}</div></div><div className="flex gap-2 mt-6"><button disabled={!roles.length || saving} onClick={() => void saveUser()} className="btn-primary flex-1 justify-center"><UserRoundCheck className="w-4 h-4" />{saving ? "Guardando…" : selected.account_status === "pending" ? "Aprobar y asignar" : "Guardar cambios"}</button>{selected.account_status === "active" && <button disabled={saving} onClick={async () => { if (confirm("¿Suspender esta cuenta y revocar sus sesiones?")) { await setUserStatus(selected.id, "suspended"); setSelected(null); load(); } }} className="btn-ghost text-p-error"><ShieldCheck className="w-4 h-4" />Suspender</button>}</div></div></div>}
  </div>;
}
