import { Navigate } from "react-router-dom";
import type { Capability } from "@/api/types";
import { can } from "@/lib/capabilities";
import { useVerbatixStore } from "@/store/useVerbatixStore";

export default function CapabilityGuard({ capability, children }: { capability: Capability; children: React.ReactNode }) {
  const user = useVerbatixStore((state) => state.user);
  return can(user, capability) ? <>{children}</> : <Navigate to="/" replace />;
}
