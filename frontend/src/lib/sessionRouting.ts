import type { UserProfile } from "@/api/types";

export function accountStateDestination(user: UserProfile, pathname: string): string | null {
  if (user.account_status === "pending" && pathname !== "/pending-approval") return "/pending-approval";
  if (user.account_status === "suspended" && pathname !== "/account-suspended") return "/account-suspended";
  if (user.account_status === "active" && user.assignments_count === 0 && !user.roles.includes("admin") && pathname !== "/no-assignments") return "/no-assignments";
  const accountStatePaths = new Set(["/pending-approval", "/no-assignments", "/account-suspended"]);
  if (user.account_status === "active" && (user.roles.includes("admin") || user.assignments_count > 0) && accountStatePaths.has(pathname)) return "/";
  return null;
}
