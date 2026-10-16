import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { ChatPage, OverviewPage } from "./App";
import { AppShell } from "@/components/AppShell";
import { AuthPage } from "@/components/AuthPage";
import { ConnectionsPage } from "@/components/ConnectionsPage";
import { PublicChat } from "@/components/PublicChat";
import { SettingsPage } from "@/components/SettingsPage";
import { authApi } from "@/lib/auth";
import { registerServiceWorker } from "@/lib/registerSW";
import { applyTheme, getThemeChoice } from "@/lib/theme";

// Fonts, bundled with the app rather than fetched from anywhere.
//
// Imported here rather than with `@import` inside index.css on purpose:
// Tailwind 4 inlines a CSS @import as text without running Vite's asset
// resolution over it, so the `url(./files/*.woff2)` references survive into the
// build unrewritten and 404 at runtime. Nothing errors — the browser just
// falls back to a system font and the real one silently never arrives.
// Importing from TypeScript hands the files to Vite, which rewrites the URLs
// and emits the woff2 files as real assets. Each subset carries a
// unicode-range, so a browser downloads only the ones a page actually uses.
import "@fontsource-variable/inter/wght.css";
import "@fontsource-variable/jetbrains-mono/wght.css";
import "./index.css";

applyTheme(getThemeChoice());
registerServiceWorker();

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  if (!authApi.isAuthenticated()) return <Navigate to="/auth" replace />;
  return <>{children}</>;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <HashRouter>
      <Routes>
        {/* Savings is the landing screen: it is the reason the product exists
            and the only view that changes on its own. Every view has a URL, so
            any of them can be bookmarked or left open on a second monitor. */}
        <Route element={<AppShell />}>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/savings" element={<OverviewPage />} />
          <Route path="/workspace" element={<ChatPage />} />
          <Route path="/connections" element={<ConnectionsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>

        {/* The signed-in chat for a shared server. */}
        <Route
          path="/chat"
          element={
            <ProtectedRoute>
              <PublicChat />
            </ProtectedRoute>
          }
        />
        <Route path="/auth" element={<AuthPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </HashRouter>
  </React.StrictMode>,
);
