import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AdminLogin } from "@/admin/AdminLogin";
import { AdminShell } from "@/admin/AdminShell";
import { Activity } from "@/admin/pages/Activity";
import { CustomerProfile } from "@/admin/pages/CustomerProfile";
import { Customers } from "@/admin/pages/Customers";
import { Messages } from "@/admin/pages/Messages";
import { Orders } from "@/admin/pages/Orders";
import { Packages } from "@/admin/pages/Packages";
import { Pricing } from "@/admin/pages/Pricing";
import { Providers } from "@/admin/pages/Providers";
import { Overview } from "@/admin/pages/Overview";
import { Users } from "@/admin/pages/Users";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { queryClient } from "@/lib/queryClient";

/**
 * The platform application.
 *
 * Nothing from the customer product is imported here -- no campaigns, leads,
 * agents or settings -- so none of it ships in this bundle.
 */
export default function AdminApp() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<AdminLogin />} />
          <Route
            element={
              <ProtectedRoute>
                <AdminShell />
              </ProtectedRoute>
            }
          >
            <Route index element={<Overview />} />
            <Route path="/customers" element={<Customers />} />
            <Route path="/customers/:id" element={<CustomerProfile />} />
            <Route path="/packages" element={<Packages />} />
            <Route path="/orders" element={<Orders />} />
            <Route path="/messages" element={<Messages />} />
            <Route path="/providers" element={<Providers />} />
            <Route path="/pricing" element={<Pricing />} />
            <Route path="/users" element={<Users />} />
            <Route path="/activity" element={<Activity />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
