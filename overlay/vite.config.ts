import { defineConfig } from "vite";

// Tauri expects a fixed dev port and no screen clearing.
export default defineConfig({
  clearScreen: false,
  // Ignore the Rust side: watching target/ crashes Vite with EBUSY on locked build outputs.
  server: { port: 1420, strictPort: true, host: "localhost", watch: { ignored: ["**/src-tauri/**"] } },
  build: { target: "es2022", outDir: "dist", emptyOutDir: true },
});
