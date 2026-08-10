import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter, Routes, Route, Navigate } from "react-router-dom";
import App from "./App";
import { PublicChat } from "@/components/PublicChat";
import { AuthPage } from "@/components/AuthPage";
import { authApi } from "@/lib/auth";
import { registerServiceWorker } from "@/lib/registerSW";

// JetBrains Mono, bundled with the app rather than fetched from anywhere.
//
// Imported here rather than with `@import` inside index.css on purpose:
// Tailwind 4 inlines a CSS @import as text without running Vite's asset
// resolution over it, so the `url(./files/*.woff2)` references survive into the
// build unrewritten and 404 at runtime. Nothing errors — the browser just
// falls back to a system mono and the font silently never arrives. Importing
// from TypeScript hands the file to Vite, which rewrites the URLs and emits the
// woff2 files as real assets.
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/700.css";
import "./index.css";

registerServiceWorker();

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
        {/* Main app — landing page */}
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
