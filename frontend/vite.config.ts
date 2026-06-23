import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend base URL is injected via VITE_API_BASE (see .env). During dev we
// also proxy /api to the backend so the frontend can call relative paths.
export default defineConfig({
  plugins: [react()],
  // Home Assistant add-on ingress serves the UI under /<addon_slug>/.
  // Relative asset URLs keep the built JS/CSS loading both at / and under
  // ingress instead of requesting /assets from the HA frontend root.
  base: "./",
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_BASE || "http://localhost:8088",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
