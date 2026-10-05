import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";

const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf-8"));

// Mobile UI: bundled into the Android app (Capacitor) and served by the
// backend under /m/.  Relative base so it works in both places.
export default defineConfig({
  root: "mobile",
  base: "./",
  plugins: [react()],
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  build: {
    outDir: "../dist/m",
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 1600,
  },
  server: { port: 5174, proxy: { "/api": process.env.SLEEPY_API || "http://127.0.0.1:8000" } },
});
