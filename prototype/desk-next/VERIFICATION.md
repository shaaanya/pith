# V5 prototype verification — 19 November 2026

This record covers `prototype/desk-next` and the authorized fixture-only prototype. It does not certify the production frontend/backend or approve a production rollout.

## Results

- Strict TypeScript check: passed.
- Isolated Vite build: passed; output is `prototype/desk-next/dist/` (approximately 273 kB JS / 16 kB CSS, before gzip). No production finalizer runs.
- Chromium: **17/17 Playwright journeys passed**, using the installed `@playwright/test` runner and its exact installed Chromium revision (1255). `evidence/test-results.json` records the project executable and results.
- Firefox **153.0** and WebKit **26.5**: **six groups of checks passed per engine**, using installed Playwright **1.62.1** and its matching Firefox revision 1538 / WebKit revision 2336. See `evidence/cross-browser.json` for actual executable paths. The primary runner explicitly skips absent exact Firefox/WebKit revisions; older binaries are never paired with that newer controller. No browser installation/download occurred.
- Empty, five-item, and 3,000-item fixtures checked in light/dark themes at 320, 375, 768, 1280 and 1440 CSS px: no document horizontal overflow. Separate 200% root-text resize at 640px and reduced-motion checks passed. These are reflow/text-resize checks, not a certification of browser zoom or mobile OS text scaling.
- Axe checked the six dataset/theme combinations and the reader: **zero serious/critical violations**. Native names/states, keyboard navigation, independent disclosures, focus containment/return and visible focus styles were also inspected. This is not a screen-reader or full WCAG conformance certification.
- Impeccable deterministic detector over App, Dialog, Reader, GroupEditor and CSS: returned `[]`. This is a mechanical check, not a substitute for visual review.

## Journeys exercised

Independent group expansion without order changes; chosen-group Focus and independent workspace expansion; local persistence; create/edit mixed membership; group removal without knowledge deletion; delayed Undo after the status message expires; deliberate keyboard/touch-friendly arrangement and Undo preserving theme; real incremental long-list continuation; related reading Back with restored scroll; honest clipboard rejection; sample loading/error recovery; mobile Search/Settings focus return (including navigation from a scrolled desk); nested membership picker scrolling on desktop and phone; missing/incomplete/edited knowledge; reel entries and evidence; reduced motion; text selection ending outside the reader; deliberate backdrop dismissal; malformed/blocked storage.

The reader was tested above a genuinely scrolled desktop with a 60-item expanded group: backdrop wheel, PageDown, reader-end wheel, dismissal, original desk scroll and original item focus. Firefox/WebKit initially failed this check. CSS containment is now supplemented with dialog-scoped wheel/touch-edge cancellation across the scrollable ancestor chain and reading-key scrolling. Native modality still owns Escape, inertness and Tab containment. Inputs, selections, control activation and zoom gestures retain their native handling. No `html`/`body` overflow/fixed-position scroll lock or second focus trap is used. Physical touch remains untested.

## Isolation

All automated Chromium journeys seed production-key sentinels and check they remain unchanged. Browser runs found no `/api` or external asset requests and no page/console errors. The app imports only its own source and installed React/icons. No auth/cookie injection, production state import, backend call, dependency/package/lockfile change, production route/build/config change was made during the original implementation. The subsequent V5 checkpoint saves these sources without changing the production application.

Tracked production diff is empty. The production dashboard HTML SHA-256 remains:

`cbcba4e4bdbdbb1247aaed03b479ff6d72b943c33e0c4c08cf36daf21d14b840`

The old `prototype/index.html` and existing user `CLAUDE.md` remain unchanged. New root `PRODUCT.md` / `DESIGN.md` record context. Existing ignored `docs/design/` references stay local; no root ignore rules were changed. Owned build/cache/reports/evidence are ignored only by `prototype/desk-next/.gitignore`.

## Review evidence and remaining limits

`evidence/review-collapsed-desktop.png`, `review-expanded-desktop.png`, `review-reader-desktop.png`, and `review-collapsed-phone.png` show the baseline and disclosure levels. The same evidence directory contains the 30 dataset/theme/width captures and engine-specific reader captures. The captures were inspected for A's compact hierarchy, wrapping, reading measure and reachable controls.

The local launcher was started successfully with `node prototype/desk-next/run.mjs` and serves only `http://127.0.0.1:5175/`. Cache, output, tests and evidence stay under this directory. Production nonce CSP is not tested by Vite.

Not yet verified: an actual Safari application, iOS/Android touch and safe-area behavior, screen-reader announcements, browser zoom UI, real extracted-content completeness, future backend group persistence, and multi-device synchronization. Loading/errors are deterministic samples. Source claims are illustrative fixture text, not fresh research. Save explains the capture boundary. Actual user evaluation of group identity, expansion whitespace and Focus/Overview usefulness is the next design gate.

Architect review accepted the final sources, screenshots and reports after corrections to persistent Undo, mobile focus return, nonzero desktop scroll and nested picker scrolling. All findings are resolved within the authorized prototype scope. The user approved saving this as V5, a working checkpoint with further refinement expected. Production integration remains a separate decision.

## V5 checkpoint quick check

On 19 November 2026, the unchanged prototype passed strict TypeScript, an isolated Vite rebuild, and all 17 Chromium journeys again before committing the checkpoint. The earlier Firefox/WebKit checks above remain the dated evidence; they were not rerun for this documentation-only checkpoint. Generated build output and browser evidence remain local and can be regenerated with the README commands.
