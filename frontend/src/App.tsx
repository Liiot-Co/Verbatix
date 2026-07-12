import { Navigate, Route, Routes } from "react-router-dom";
import AppShell from "@/components/AppShell";
import ProjectDashboard from "@/components/ProjectDashboard";
import ProjectDetail from "@/components/ProjectDetail";
import CreationWizard from "@/components/CreationWizard";
import VerbatimsTable from "@/components/VerbatimsTable";
import ToastStack from "@/components/ToastStack";
import { CommandPalette } from "@/components/CommandPalette";

export default function App() {
  return (
    <AppShell>
      <main className="flex-1 px-6 py-8 overflow-y-auto min-h-0 scrollbar-thin">
        <Routes>
          <Route path="/" element={<ProjectDashboard />} />
          <Route path="/projects/:projectId" element={<ProjectDetail />} />
          <Route path="/wizard" element={<CreationWizard />} />
          <Route path="/rounds/:roundId/verbatims" element={<VerbatimsTable />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <ToastStack />
      <CommandPalette />
    </AppShell>
  );
}
