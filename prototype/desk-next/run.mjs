import { createServer } from "../../frontend/node_modules/vite/dist/node/index.js";
import { fileURLToPath } from "node:url";
const server = await createServer({
  configFile: fileURLToPath(new URL("./vite.config.mjs", import.meta.url)),
  configLoader: "native",
});
await server.listen();
server.printUrls();
for (const signal of ["SIGINT", "SIGTERM"])
  process.once(signal, async () => {
    await server.close();
    process.exit(0);
  });
