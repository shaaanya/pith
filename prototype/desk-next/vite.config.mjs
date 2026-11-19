import { defineConfig } from "../../frontend/node_modules/vite/dist/node/index.js";
import react from "../../frontend/node_modules/@vitejs/plugin-react/dist/index.js";
import { fileURLToPath } from "node:url";
const here = fileURLToPath(new URL(".", import.meta.url));
const dependency = (name) =>
  fileURLToPath(
    new URL(`../../frontend/node_modules/${name}`, import.meta.url),
  );
export default defineConfig({
  root: here,
  cacheDir: `${here}.cache`,
  plugins: [react()],
  resolve: {
    alias: ["react", "react-dom", "lucide-react"].map((name) => ({
      find: name,
      replacement: dependency(name),
    })),
  },
  server: {
    host: "127.0.0.1",
    port: 5175,
    strictPort: true,
    fs: { allow: [here, dependency("")] },
  },
  build: { outDir: `${here}dist`, emptyOutDir: true, target: "es2022" },
});
