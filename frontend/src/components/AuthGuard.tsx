import { Navigate, useLocation } from "react-router-dom";
import { useVerbatixStore } from "@/store/useVerbatixStore";

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useVerbatixStore((s) => s.isAuthenticated);
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <>{children}</>;
}
