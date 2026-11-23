import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

const DAEMON_TARGET = process.env.VITE_LATTIS_PROXY_TARGET || "http://127.0.0.1:7700";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src")
    }
  },
  build: {
    outDir: "../lattis/web/static",
    emptyOutDir: true
  },
  server: {
    port: 5173,
    allowedHosts: ["binal"],
    proxy: {
      "/health": DAEMON_TARGET,
      "/info": DAEMON_TARGET,
      "/agents": DAEMON_TARGET,
      "/workspaces": DAEMON_TARGET,
      "/threads": DAEMON_TARGET,
      "/runs": DAEMON_TARGET,
      "/events": {
        target: DAEMON_TARGET,
        changeOrigin: true
      }
    }
  }
});
