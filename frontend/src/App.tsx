import { Navigate, Route, Routes } from "react-router-dom";
import AppShell from "@/components/AppShell";
import AuthGuard from "@/components/AuthGuard";
import SignInPage from "@/components/SignInPage";
import SignUpPage from "@/components/SignUpPage";
import ProjectDashboard from "@/components/ProjectDashboard";
import ProjectDetail from "@/components/ProjectDetail";
import CreationWizard from "@/components/CreationWizard";
import UnifiedStudioView from "@/components/UnifiedStudioView";
import AuditView from "@/components/AuditView";
import ReportView from "@/components/ReportView";
import ToastStack from "@/components/ToastStack";
import { CommandPalette } from "@/components/CommandPalette";

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/login" element={<SignInPage />} />
        <Route path="/signup" element={<SignUpPage />} />
        <Route
          path="/*"
          element={
            <AuthGuard>
              <AppShell>
                <main className="flex-1 px-6 py-8 overflow-y-auto min-h-0 scrollbar-thin">
                  <Routes>
                    <Route path="/" element={<ProjectDashboard />} />
                    <Route path="/projects/:projectId" element={<ProjectDetail />} />
                    <Route path="/wizard" element={<CreationWizard />} />
                    <Route path="/rounds/:roundId" element={<UnifiedStudioView />} />
                    <Route path="/rounds/:roundId/preliminary" element={<UnifiedStudioView />} />
                    <Route path="/rounds/:roundId/verbatims" element={<UnifiedStudioView />} />
                    <Route path="/rounds/:roundId/audit" element={<AuditView />} />
                    <Route path="/rounds/:roundId/report" element={<ReportView />} />
                    <Route path="*" element={<Navigate to="/" replace />} />
                  </Routes>
                </main>
                <CommandPalette />
              </AppShell>
            </AuthGuard>
          }
        />
      </Routes>
      <ToastStack />
    </>
  );
}
