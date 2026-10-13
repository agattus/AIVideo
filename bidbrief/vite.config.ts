import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Served at /bidbrief on the Render-hosted AIVideo API.
  base: process.env.BIDBRIEF_BASE || "/",
  server: {
    port: 5174,
    host: true,
  },
  preview: {
    port: 4173,
    host: true,
    allowedHosts: true,
  },
});
