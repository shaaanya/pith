// Post-build: turn dist/index.html into the file the Python server serves.
// - every inline <script>/<style> gets the per-response nonce placeholder the server replaces
// - asserts the CSP invariants (no external hosts, no linked assets, no dangerous sinks)
// - writes src/pith/dashboard/static/index.html
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = (p) => fileURLToPath(new URL(p, import.meta.url));
let html = readFileSync(root("../dist/index.html"), "utf8");

html = html
  .replace(/<script\b([^>]*)>/g, (_, a) => `<script nonce="{{nonce}}"${a.replace(/\s*crossorigin(="[^"]*")?/g, "")}>`)
  .replace(/<style\b([^>]*)>/g, (_, a) => `<style nonce="{{nonce}}"${a}>`);

const problems = [];
if (/<link\b[^>]*(href|rel)=/i.test(html)) problems.push("<link> present: the server cannot serve linked assets");
if (/<script\b[^>]*\ssrc=/i.test(html)) problems.push("<script src> present");
if (/\b(?:src|href)=["']https?:/i.test(html)) problems.push("external URL in markup");
if (/url\(\s*["']?(?:https?:|data:)/i.test(html)) problems.push("external or data: url() in CSS (CSP blocks it)");
const tags = html.match(/<(script|style)\b[^>]*>/g) ?? [];
for (const t of tags) if (!t.includes('nonce="{{nonce}}"')) problems.push(`tag without nonce: ${t}`);
if (!html.includes("{{nonce}}")) problems.push("no nonce placeholder");
if (problems.length) {
  console.error("finalize: " + problems.join("\n  "));
  process.exit(1);
}
writeFileSync(root("../../src/pith/dashboard/static/index.html"), html);
console.log(`finalize: wrote static/index.html (${(html.length / 1024).toFixed(0)} KB, ${tags.length} inline tags)`);
