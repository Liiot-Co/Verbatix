import type { RoleCode } from "@/api/types";

const LABELS: Record<RoleCode, string> = { admin: "Admin", codificador: "Codificador", supervisor: "Supervisor" };

export default function RoleBadge({ role }: { role: RoleCode }) {
  return <span className="chip text-[10px]">{LABELS[role]}</span>;
}
