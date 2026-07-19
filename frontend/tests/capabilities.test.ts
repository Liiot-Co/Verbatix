import { describe, expect, test } from "bun:test";
import { can, hasRole } from "../src/lib/capabilities";
import type { UserProfile } from "../src/api/types";
import { accountStateDestination } from "../src/lib/sessionRouting";
import { decodeStoredToken } from "../src/lib/tokenStorage";

const user = (roles: UserProfile["roles"], capabilities: UserProfile["capabilities"]): UserProfile => ({
  id: "1", email: "person@example.test", name: "Person", roles, capabilities,
  account_status: "active", presence_status: "disponible", presence_changed_at: null,
  assignments_count: 1, created_at: "2026-07-18T00:00:00Z",
});

describe("account state guard", () => {
  test("routes pending and suspended sessions to explicit states", () => {
    expect(accountStateDestination({ ...user([], []), account_status: "pending", assignments_count: 0 }, "/")).toBe("/pending-approval");
    expect(accountStateDestination({ ...user([], []), account_status: "suspended", assignments_count: 0 }, "/")).toBe("/account-suspended");
  });

  test("lets active members without assignments use home and inbox", () => {
    expect(accountStateDestination({ ...user(["codificador"], []), assignments_count: 0 }, "/")).toBeNull();
    expect(accountStateDestination({ ...user(["codificador"], []), assignments_count: 0 }, "/notifications")).toBeNull();
    expect(accountStateDestination({ ...user(["codificador"], []), assignments_count: 0 }, "/projects/abc")).toBe("/");
    expect(accountStateDestination({ ...user(["codificador"], []), assignments_count: 0 }, "/no-assignments")).toBe("/");
    expect(accountStateDestination({ ...user(["admin"], []), assignments_count: 0 }, "/")).toBeNull();
  });

  test("does not loop when already on the matching state page", () => {
    const pending = { ...user([], []), account_status: "pending" as const, assignments_count: 0 };
    expect(accountStateDestination(pending, "/pending-approval")).toBeNull();
  });

  test("leaves account-state pages after coder or supervisor receives a project", () => {
    expect(accountStateDestination({ ...user(["codificador"], []), assignments_count: 1 }, "/no-assignments")).toBe("/");
    expect(accountStateDestination({ ...user(["supervisor"], []), assignments_count: 1 }, "/pending-approval")).toBe("/");
  });
});

describe("token storage compatibility", () => {
  test("reads raw and legacy JSON-encoded opaque tokens without quotes", () => {
    expect(decodeStoredToken("opaque-token")).toBe("opaque-token");
    expect(decodeStoredToken('"opaque-token"')).toBe("opaque-token");
    expect(decodeStoredToken(null)).toBeNull();
  });
});

describe("capability helpers", () => {
  test("uses backend capabilities as the only action source", () => {
    const coder = user(["codificador"], ["resolution.view", "resolution.edit", "audit.view", "audit.edit", "reports.view", "reports.export"]);
    expect(can(coder, "resolution.view")).toBe(true);
    expect(can(coder, "resolution.edit")).toBe(true);
    expect(can(coder, "rounds.manage")).toBe(false);
    expect(can(coder, "audit.approve")).toBe(false);
  });

  test("keeps resolution separate from supervisor-only access", () => {
    const supervisor = user(["supervisor"], ["audit.view", "audit.edit", "audit.approve", "reports.view", "reports.export"]);
    expect(can(supervisor, "resolution.view")).toBe(false);
    expect(can(supervisor, "rounds.manage")).toBe(false);
  });

  test("supports cumulative roles without inventing permissions", () => {
    const combined = user(["codificador", "supervisor"], ["resolution.view", "audit.view", "audit.approve"]);
    expect(hasRole(combined, "codificador")).toBe(true);
    expect(hasRole(combined, "supervisor")).toBe(true);
    expect(can(combined, "projects.manage")).toBe(false);
  });

  test("denies when the session has no profile", () => {
    expect(can(null, "reports.view")).toBe(false);
  });
});
