import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter, Routes, Route, Navigate } from "react-router-dom";
import App from "./App";
import { PublicChat } from "@/components/PublicChat";
import { AuthPage } from "@/components/AuthPage";
import { authApi } from "@/lib/auth";
import "./index.css";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  if (!authApi.isAuthenticated()) {
    return <Navigate to="/auth" replace />;
  }
  return <>{children}</>;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <HashRouter>
      <Routes>
        {/* Main app — devpanel is the landing page */}
        <Route path="/" element={<App />} />

        {/* Public chat — accessible under Jakobs Stuff */}
        <Route path="/chat" element={
          <ProtectedRoute>
            <PublicChat />
          </ProtectedRoute>
        } />

        {/* Auth page */}
        <Route path="/auth" element={<AuthPage />} />

        {/* Catch-all redirect to home */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </HashRouter>
  </React.StrictMode>
);
