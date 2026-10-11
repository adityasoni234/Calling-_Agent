import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import AdminApp from "@/admin/AdminApp";
import "@/index.css";

const container = document.getElementById("root");
if (!container)
  throw new Error("Root element #root is missing from admin.html");

createRoot(container).render(
  <StrictMode>
    <AdminApp />
  </StrictMode>,
);
