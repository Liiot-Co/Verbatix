import type { UserProfile } from "@/api/types";

/** Active non-admin with roles but no project assignments yet. */
export function isWaitingForAssignments(user: UserProfile): boolean {
  return user.account_status === "active" && user.assignments_count === 0 && !user.roles.includes("admin");
}

const WAITING_ALLOWED = new Set(["/", "/notifications"]);

export function accountStateDestination(user: UserProfile, pathname: string): string | null {
  if (user.account_status === "pending" && pathname !== "/pending-approval") return "/pending-approval";
  if (user.account_status === "suspended" && pathname !== "/account-suspended") return "/account-suspended";

  if (isWaitingForAssignments(user)) {
    // Legacy bookmark → home inside the shell
    if (pathname === "/no-assignments") return "/";
    if (WAITING_ALLOWED.has(pathname)) return null;
    return "/";
  }

  const accountStatePaths = new Set(["/pending-approval", "/no-assignments", "/account-suspended"]);
  if (user.account_status === "active" && accountStatePaths.has(pathname)) return "/";
  return null;
}
