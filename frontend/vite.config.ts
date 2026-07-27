import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(root, "./src"),
    },
  },
  build: {
    // The bundle used to be one 336 kB chunk. Splitting the markdown renderer
    // and the icon set out means the first paint no longer waits on them.
    // Vite 8 bundles with Rolldown, which only accepts the function form.
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (!id.includes("node_modules")) return undefined;
          if (/[\\/]node_modules[\\/](react|react-dom|react-router|react-router-dom)[\\/]/.test(id))
            return "react";
          if (id.includes("react-markdown") || id.includes("remark") || id.includes("micromark"))
            return "markdown";
          if (id.includes("lucide-react")) return "icons";
          return undefined;
        },
      },
    },
    chunkSizeWarningLimit: 250,
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      "/api": {
        target: "http://localhost:7000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
