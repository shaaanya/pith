# Pith Home V5 — contextual desk checkpoint

**Status: working design checkpoint, approved to save by the user on 19 November 2026. Further refinement is expected.**

Prototype: [`desk-next/`](desk-next/README.md). Run `node prototype/desk-next/run.mjs` from the repository root, then open **http://127.0.0.1:5175/**. It reuses dependencies installed in `frontend/`; no separate installation is needed. The earlier V4 prototype remains in `prototype/index.html` with its own notes.

## Design direction

Everything should be easy to reach. Not everything needs to be visible simultaneously.

**Collapsed groups → compact expanded item list → complete item overlay.**

The supplied Stitch Collapsed Home (State A) governs the calm composition: warm paper, restrained rust accents, system serif page/reading typography, system sans controls, and a two-column row-major map on wide screens. Shallow bounded groups and optional descriptors provide collection identity without document previews. B1 informs local expansion; B2's full-width promotion/reordering is rejected. C informs complete reading without a mandatory second reader or permanent third column. Codex owns refinement; no further Stitch work is planned.

Home groups are flexible contexts and may contain different knowledge kinds. Shelves remain purpose-based places for long-term retrieval. No artificial productivity scores, urgency, completion pressure, or automatic group rearrangement.

## Working interactions

- Groups expand independently in place; opening one leaves others open. The default list shows five items with real remaining counts and incremental continuation for large groups. Natural expansion moves later rows vertically while preserving order and columns; it does not promote or repack groups.
- Overview shows all groups. Focus shows only groups explicitly chosen by the user, in the same relative order, with independent expansion state. There is no arbitrary three-group limit.
- Item selection opens complete illustrative knowledge: prose, commands, entries, evidence, honest gaps and related notes. Related navigation stays inside one dialog; Back restores reading position. Close/Escape returns to the item and desk position.
- Create/edit controls change group name, context and membership locally. Removing a group never deletes its items. Arrange exposes Move up/down for keyboard and touch; Undo remains reachable after the announcement expires.
- Search and Shelves browse fixtures. Save explains the capture boundary. Settings provide empty/sparse/rich collections, light/dark themes, loading/error examples and reset.

## Accessibility and responsive structure

Real heading/disclosure buttons expose expanded state. Native dialog owns modality, Escape and focus containment; explicit opener identity restores focus, including browsers where pointer clicks do not focus buttons. Scoped scroll handling protects the background while allowing nested picker scrolling; no root scrollbar lock or second focus trap is used.

The rail collapses to a reachable navigation menu at narrower widths; groups become one column as content requires. The phone reader fills the viewport. Controls target 44px, text wraps, reading measure is about 68ch, and reduced motion removes transitions without removing feedback.

## Data and build boundary

This is an isolated frontend prototype with illustrative fixtures, including a five-item collection and a 3,000-item library with a long group. All changes use only `pith.prototype.desk-next.v1` on the separate strict loopback port. Blocked storage falls back to visit-local memory. There are no Pith API calls, production state imports, credentials, backend changes or package/lockfile changes.

Runtime, tests, config, cache and build output belong to `prototype/desk-next/`. Generated output/evidence are ignored. Production frontend/backend and the previous V4 remain unchanged. This checkpoint does not replace the production dashboard.

## Verification and next decisions

See [`desk-next/VERIFICATION.md`](desk-next/VERIFICATION.md) for detailed evidence and limits. The original build passed strict TypeScript, isolated Vite build, 17 Chromium journeys, axe checks across data/theme states, and six check groups each in matching installed Firefox/WebKit. Quick checkpoint verification is recorded there separately.

Next design work: evaluate group recognition and descriptors, expansion whitespace, Focus/Overview usefulness, and the complete reading experience with the user. Physical touch, actual OS Safari, screen readers, real extraction fidelity, production nonce CSP, group persistence APIs and cross-device synchronization remain outside verified prototype support. Production integration needs its own implementation plan.

The raw Stitch HTML, skill inventory, audit and detailed initial brief are local supplemental artifacts under ignored `docs/design/`. This tracked document preserves the checkpoint's decisions and run instructions independently of those files. Product and visual context also live in root `PRODUCT.md` and `DESIGN.md`.
