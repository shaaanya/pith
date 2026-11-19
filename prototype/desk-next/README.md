# Pith Home V5 — desk prototype

A working design checkpoint, approved to save on 19 November 2026; further refinement is expected.

An isolated, interactive interpretation of the reviewed A/B/C references. Open a contextual group, choose an item, read its complete knowledge, and return to your desk. Multiple groups stay open; Focus contains groups you choose.

Run from the repository root using the already installed frontend dependencies:

```sh
node prototype/desk-next/run.mjs
```

Open **http://127.0.0.1:5175/**. Stop with Ctrl+C. The server binds loopback only and refuses to move to another port. `run.mjs` uses native config loading to avoid Vite's config-bundle cache outside this directory.

Try:

1. Open Tools to Check Out, then another group. Choose an item and press Escape to return.
2. Open a group's options and Add to Focus. Switch workspaces; each remembers its own open groups.
3. Create/edit a mixed group, choose its items, or use Arrange's Move up/down controls. Undo reverses the last organization change.
4. Follow a related item inside the reader, then Back to restore your reading position. Copy a command or open its source.
5. Use Example collection & appearance for empty/sparse/rich data, light/dark themes, sample loading/error recovery, or reset.

Search and Shelves browse the fixture library. Save explains the capture boundary; this prototype does not upload or save new sources. Nothing calls Pith's API. All content is illustrative; organization uses only `pith.prototype.desk-next.v1` on this separate origin. Blocked storage falls back to this visit's memory. Reset touches only this prototype's state.

Verification commands, from the repository root:

```sh
pnpm --dir frontend exec tsc --project ../prototype/desk-next/tsconfig.json --noEmit
pnpm --dir frontend exec vite build --config ../prototype/desk-next/vite.config.mjs --configLoader native
pnpm --dir frontend exec playwright test --config ../prototype/desk-next/playwright.config.mjs
node prototype/desk-next/cross-browser.mjs
```

The primary test runner uses only exact installed browser revisions and reports missing engines explicitly. Chromium runs the full suite. On this machine, Firefox/WebKit are checked by `cross-browser.mjs` with the already installed Playwright runtime that matches their binaries; incompatible controllers/binaries are never paired. Nothing downloads browsers. Reports record actual versions/paths. These checks do not certify an installed Safari application or mobile OS.

Native dialog owns focus containment, inertness and Escape. CSS overscroll containment is supplemented by scoped scroll-gesture/reading-key handling because tested Firefox/WebKit otherwise scrolled the desk behind a modal. No root scrollbar lock is applied.

Build output/cache, screenshots, reports, and tests stay under this directory. Production routes, package/lockfiles, backend, static HTML, and the earlier `prototype/index.html` remain unchanged. No production build/finalizer runs. This prototype's Vite asset serving is not a test of production nonce CSP.

See [the V5 checkpoint](../HOME-V5.md) for decisions and [VERIFICATION.md](VERIFICATION.md) for actual checks and remaining limits.
