import { useEffect } from "react";
import { Navigate, useLocation } from "react-router-dom";
import Loader from "@/components/Loader";
import { useVerbatixStore } from "@/store/useVerbatixStore";
import { accountStateDestination } from "@/lib/sessionRouting";

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, sessionReady, hydrateSession, user } = useVerbatixStore();
  const location = useLocation();

  useEffect(() => {
    if (!sessionReady) void hydrateSession();
  }, [hydrateSession, sessionReady]);

  if (!sessionReady) return <div className="min-h-screen grid place-items-center bg-p-bg"><Loader /></div>;
  if (!isAuthenticated || !user) return <Navigate to="/login" state={{ from: location }} replace />;
  const accountDestination = accountStateDestination(user, location.pathname);
  if (accountDestination) return <Navigate to={accountDestination} replace />;
  return <>{children}</>;
}
