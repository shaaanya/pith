# Pith design context

## Authority and scope

The user's supplied State A is the primary visual baseline for V5 and its product implementation: warm, restrained, editorial, and compact. B1 supplies a local expansion reference, C a reading overlay reference. Their exported code is not production code. The user's explicit choices and the tracked [V5 checkpoint](prototype/HOME-V5.md) govern behavior. The detailed initial brief and raw references under ignored docs/design/ remain local supplemental evidence.

The incumbent frontend uses paper/graphite/rust tokens, system serif for knowledge, system sans for controls, light/dark themes, and container-aware layout (frontend/src/index.css). This document records that context and the reviewed prototype direction; V5 is now implemented in the production shell and desk, with real data and existing product workflows.

## Composition

Preserve A's quiet navigation, search bar, 32px serif page heading, generous surrounding space, and row-major two-column group index on wide content containers. Group titles remain 16px sans. Refined collapsed groups stay near 52–68px minimum height, growing with text. One soft boundary and an optional descriptor identify the collection without turning it into a summary card. No masonry, automatic promotion, or selection-driven reorder.

## Tokens and hierarchy

Use semantic paper, inset, raised, ink, soft, muted, line, accent and accent-tint roles. The prototype interprets the reference palette with contrast-corrected muted text: warm paper #fff8f3, inset #f7f1eb, ink #24201d, muted #75625a, rust #9d3d26. Dark mode preserves the same hierarchy, with desaturated rust and warm neutral surfaces. These values now apply to the V5 product shell and desk through semantic production tokens.

System sans, system serif, and system mono only. Mono is reserved for real commands. Use a 4px spacing scale for new components; reference layout gutters may remain 28px. Comfortable 44px control targets, visible rust focus rings, readable metadata, and approximately 68ch reading measure matter more than reproducing microtype.

## Interactions

Collapsed group → compact list → complete extracted knowledge in a native modal dialog. Group headings contain real disclosure buttons. Multiple groups open independently. Focus is a chosen subset of groups in the same relative order as Overview. Organization is explicit and undoable. Closing knowledge preserves the desk and opener.

Use native semantics and installed libraries. Product organization uses revision-checked database snapshots; prototype state remains isolated. No group-height animation, page choreography, decorative blur, arbitrary dots, or heavy gradients. Brief opacity/color feedback may run with normal motion; reduced motion changes state immediately without removing focus/status feedback.

## Validation

Test empty/sparse/rich fixtures, mixed knowledge kinds, narrow/zoomed layouts, keyboard paths, contrast, native dialog focus/return, copy failure, storage failure, and isolation. Prototype browser checks do not validate production nonce CSP. Safari/Firefox and screen-reader support must be stated according to actual evidence, not assumed.
