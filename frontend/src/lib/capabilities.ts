import type { Capability, UserProfile } from "@/api/types";

export function can(user: UserProfile | null, capability: Capability): boolean {
  return user?.capabilities.includes(capability) ?? false;
}

export function hasRole(user: UserProfile | null, role: UserProfile["roles"][number]): boolean {
  return user?.roles.includes(role) ?? false;
}
