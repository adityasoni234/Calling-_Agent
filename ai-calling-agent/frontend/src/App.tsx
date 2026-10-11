import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppLayout } from "@/components/AppLayout";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { queryClient } from "@/lib/queryClient";
import { AgentsPage } from "@/pages/AgentsPage";
import { ApiPage } from "@/pages/ApiPage";
import { BillingPage } from "@/pages/BillingPage";
import { CallDetailPage, CallsPage } from "@/pages/CallsPage";
import { CampaignDetailPage, CampaignsPage } from "@/pages/CampaignsPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { KnowledgePage } from "@/pages/KnowledgePage";
import { LeadsPage } from "@/pages/LeadsPage";
import { LearningPage } from "@/pages/LearningPage";
import { LoginPage } from "@/pages/LoginPage";
import { ManualCallPage } from "@/pages/ManualCallPage";
import { MessagesPage } from "@/pages/MessagesPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { QualifiedPage } from "@/pages/QualifiedPage";
import { RegisterPage } from "@/pages/RegisterPage";
import { SettingsPage } from "@/pages/SettingsPage";

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />

          <Route
            element={
              <ProtectedRoute>
                <AppLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<DashboardPage />} />
            <Route path="/agents" element={<AgentsPage />} />
            <Route path="/learning" element={<LearningPage />} />
            <Route path="/leads" element={<LeadsPage />} />
            <Route path="/qualified" element={<QualifiedPage />} />
            <Route path="/campaigns" element={<CampaignsPage />} />
            <Route path="/campaigns/:id" element={<CampaignDetailPage />} />
            <Route path="/calls" element={<CallsPage />} />
            <Route path="/manual" element={<ManualCallPage />} />
            <Route path="/messages" element={<MessagesPage />} />
            <Route path="/calls/:id" element={<CallDetailPage />} />
            <Route path="/knowledge" element={<KnowledgePage />} />
            <Route path="/api" element={<ApiPage />} />
            <Route path="/billing" element={<BillingPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/404" element={<NotFoundPage />} />
          </Route>

          <Route path="*" element={<Navigate to="/404" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
