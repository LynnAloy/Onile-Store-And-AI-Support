import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import vueDevTools from "vite-plugin-vue-devtools";

export default defineConfig({
  server: {
    port: 3000,
    proxy: {
      "/api": { target: process.env.JAVA_PROXY_TARGET || "http://127.0.0.1:8080", changeOrigin: true },
      "/ai": { target: process.env.AI_PROXY_TARGET || "http://127.0.0.1:8000", changeOrigin: true, timeout: 260000 },
    },
  },
  plugins: [vue(), ...(process.env.ENABLE_VUE_DEVTOOLS === "true" ? [vueDevTools()] : [])],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
});
