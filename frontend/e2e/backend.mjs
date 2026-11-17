// Starts a REAL Pith backend on a throwaway home (never ~/Pith), seeds it through the public API,
// and stays alive for Playwright. Used as `webServer.command`; killed with the test run.
//  - heuristic backend only: deterministic, no model needed
//  - the watch folder lives inside the temp home, so nothing outside it is read or created
//  - a .mp4 with no transcriber configured lands in "needs you" (a real attention state)
import { spawn } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const PORT = Number(process.env.E2E_PORT ?? 8793);
export const TOKEN = "e2e-token-0123456789";
const repo = resolve(import.meta.dirname, "../..");
const home = mkdtempSync(join(tmpdir(), "pith-e2e-"));
mkdirSync(join(home, "inbox"), { recursive: true });
writeFileSync(join(home, "http_token"), TOKEN, { mode: 0o600 });
writeFileSync(
  join(home, "config.toml"),
  `[backends.heuristic]\ntype = "heuristic"\n\n[tasks]\ndistill = ["heuristic"]\nclassify = ["heuristic"]\n\n[watch]\ndirs = ["${join(home, "inbox")}"]\n\n[http]\nport = ${PORT + 100}\n`,
);

const child = spawn("uv", ["run", "pith", "--home", home, "run", "--port", String(PORT), "--no-open"], {
  cwd: repo,
  stdio: ["ignore", "inherit", "inherit"],
});
const stop = () => child.kill("SIGTERM");
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
child.on("exit", (c) => process.exit(c ?? 0));

const base = `http://127.0.0.1:${PORT}`;
const headers = { "X-Token": TOKEN };
const post = (body) =>
  fetch(`${base}/api/inbox`, { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(body) });
const get = async (p) => (await fetch(base + p, { headers })).json();

for (let i = 0; ; i++) {
  try {
    if ((await fetch(base + "/favicon.ico")).ok) break;
  } catch {
    /* not up yet */
  }
  if (i > 100) throw new Error("backend did not start");
  await new Promise((r) => setTimeout(r, 300));
}

const NOTES = [
  [
    "Postgres logical replication. 1. Set wal_level=logical on the primary and restart. 2. CREATE PUBLICATION app_pub FOR ALL TABLES; 3. On the replica run CREATE SUBSCRIPTION app_sub CONNECTION 'host=10.0.0.5 dbname=app' PUBLICATION app_pub; Warning: sequences are not replicated. The tool pgbadger reads the Postgres logs.",
    "migrate the database",
  ],
  ["Sourdough starter feeding: keep 50g starter, add 50g flour and 50g water at 24C. It doubles in 4 to 6 hours.", "weekend baking"],
  [
    "Rust ownership: each value has one owner and borrows must not outlive it. The crate cargo-flamegraph profiles hot paths.",
    "learning rust",
  ],
  ["Espresso dial in: 18g in, 36g out, 28 to 30 seconds. If sour, grind finer. Tip: a bottomless portafilter shows channeling.", ""],
  [
    "Kubernetes debugging: kubectl describe pod, then kubectl logs --previous. Exit code 137 usually means OOMKilled, so raise the memory limit. The tool k9s is a terminal UI for clusters.",
    "oncall",
  ],
  ["Tokyo trip: a Suica card works on all metro lines. Teamlab Planets needs a timed ticket booked 3 weeks ahead.", "trip in March"],
];
for (const [text, context] of NOTES) await post({ text, ...(context ? { context } : {}) });
// Many small notes so the library has more than one page and needs virtualization.
for (let i = 0; i < 70; i++)
  await post({ text: `Bulk note ${i} about topic${i % 5}. Step one configure widget${i}. Step two verify marker zq${i}x.` });

const form = new FormData();
form.set("file", new Blob([readFileSync(join(repo, "frontend/e2e/fixtures/reel.mp4"))], { type: "video/mp4" }), "pasta-reel.mp4");
form.set("context", "a pasta trick from a reel");
await fetch(`${base}/api/inbox`, { method: "POST", headers, body: form });
// A blank file: "empty content", which pasted text CAN fix (the reel above cannot: no transcriber).
const blank = new FormData();
blank.set("file", new Blob(["   \n  \n"]), "blank-notes.txt");
await fetch(`${base}/api/inbox`, { method: "POST", headers, body: blank });

for (let i = 0; i < 200; i++) {
  const s = await get("/api/state");
  if ((s.counts.pending ?? 0) + (s.counts.processing ?? 0) + (s.counts.new ?? 0) === 0) break;
  await new Promise((r) => setTimeout(r, 500));
}
console.log(`e2e backend ready on ${base} (home ${home})`);
await new Promise(() => {});
