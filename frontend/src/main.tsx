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
        {/* Savings is the landing screen. It is the reason the product exists
            and the only view that changes on its own; the chat is a feature of
            it rather than the other way round. Both have a URL now, so either
            can be bookmarked or left open on a second monitor — the dashboard
            used to be component state reachable only by clicking through. */}
        <Route path="/" element={<App initialView="savings" />} />
        <Route path="/savings" element={<App initialView="savings" />} />
        <Route path="/workspace" element={<App initialView="chat" />} />

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
