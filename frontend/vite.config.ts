import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend serves the built files; during development the Vite dev server
// proxies /api to a locally running backend (default http://127.0.0.1:8000).
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 1600,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes("node_modules/echarts") || id.includes("node_modules/zrender")) return "echarts";
          if (id.includes("node_modules")) return "vendor";
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: { "/api": process.env.SLEEPY_API || "http://127.0.0.1:8000" },
  },
});
