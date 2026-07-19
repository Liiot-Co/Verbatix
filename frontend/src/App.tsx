import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import AppShell from "@/components/AppShell";
import AuthGuard from "@/components/AuthGuard";
import SignInPage from "@/components/SignInPage";
import SignUpPage from "@/components/SignUpPage";
import RecoverAccountPage from "@/components/RecoverAccountPage";
import AccountStatePage from "@/components/AccountStatePage";
import TeamAdminPage from "@/components/TeamAdminPage";
import CapabilityGuard from "@/components/CapabilityGuard";
import ProjectDashboard from "@/components/ProjectDashboard";
import ProjectDetail from "@/components/ProjectDetail";
import CreationWizard from "@/components/CreationWizard";
import AddLoadView from "@/components/AddLoadView";
import UnifiedStudioView from "@/components/UnifiedStudioView";
import AuditView from "@/components/AuditView";
import ReportView from "@/components/ReportView";
import ToastStack from "@/components/ToastStack";
import { CommandPalette } from "@/components/CommandPalette";
import NotificationsInbox from "@/components/NotificationsInbox";
import NotificationToast from "@/components/NotificationToast";
import { prepareNotificationSound } from "@/lib/sound";

export default function App() {
  useEffect(() => prepareNotificationSound(), []);

  return (
    <>
      <Routes>
        <Route path="/login" element={<SignInPage />} />
        <Route path="/signup" element={<SignUpPage />} />
        <Route path="/forgot-password" element={<RecoverAccountPage intro />} />
        <Route path="/recover-account" element={<RecoverAccountPage />} />
        <Route path="/pending-approval" element={<AuthGuard><AccountStatePage state="pending" /></AuthGuard>} />
        <Route path="/no-assignments" element={<Navigate to="/" replace />} />
        <Route path="/account-suspended" element={<AuthGuard><AccountStatePage state="suspended" /></AuthGuard>} />
        <Route
          path="/*"
          element={
            <AuthGuard>
              <AppShell>
                <main className="flex-1 px-6 py-8 overflow-y-auto min-h-0 scrollbar-thin">
                  <Routes>
                    <Route path="/" element={<ProjectDashboard />} />
                    <Route path="/projects/:projectId" element={<ProjectDetail />} />
                    <Route path="/wizard" element={<CapabilityGuard capability="projects.manage"><CreationWizard /></CapabilityGuard>} />
                    <Route path="/team" element={<CapabilityGuard capability="users.manage"><TeamAdminPage /></CapabilityGuard>} />
                    <Route path="/notifications" element={<NotificationsInbox />} />
                    <Route path="/rounds/:roundId/add-load" element={<CapabilityGuard capability="rounds.manage"><AddLoadView /></CapabilityGuard>} />
                    <Route path="/rounds/:roundId" element={<UnifiedStudioView />} />
                    <Route path="/rounds/:roundId/preliminary" element={<UnifiedStudioView />} />
                    <Route path="/rounds/:roundId/verbatims" element={<UnifiedStudioView />} />
                    <Route path="/rounds/:roundId/audit" element={<CapabilityGuard capability="audit.view"><AuditView /></CapabilityGuard>} />
                    <Route path="/rounds/:roundId/report" element={<CapabilityGuard capability="reports.view"><ReportView /></CapabilityGuard>} />
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
      <NotificationToast />
    </>
  );
}
