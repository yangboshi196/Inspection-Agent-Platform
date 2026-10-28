import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import path from "path";

export default defineConfig({
  plugins: [react()],
  base: "./",
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src/hermes_agent"),
      "@hermes": path.resolve(__dirname, "src/hermes_agent"),
    },
  },
  server: {
    host: true, // 监听 0.0.0.0，允许局域网/外网通过本机 IP 访问
    port: 5173,
    proxy: {
      "/api/hermes": {
        target: "http://127.0.0.1:8010",
        changeOrigin: true,
        ws: true,
        rewrite: (p) => p.replace(/^\/api\/hermes/, "/hermes-agent"),
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq) => {
            // Let Hermes rewrite absolute /assets URLs to /api/hermes/assets
            // in index.html during local dev proxying.
            proxyReq.setHeader("x-forwarded-prefix", "/api/hermes");
          });
        },
      },
      "/api": { target: "http://127.0.0.1:8010", changeOrigin: true, ws: true },
      "/data": { target: "http://127.0.0.1:8010", changeOrigin: true },
    },
  },
  build: {
    outDir: "../inspection_platform/static",
    emptyOutDir: true,
  },
});
