# Pith

<!-- impeccable:product-schema 1 -->

## Platform

web

## Product purpose and users

Pith is a local-first personal knowledge base. A person saves links, videos, PDFs, screenshots, and voice notes; Pith turns sources into searchable knowledge with evidence. The dashboard is a reading room for returning to that material. Product facts come from README.md, docs/capabilities.md, and the user's design handoff; no new audience or commercial claims are inferred.

## Capabilities and constraints

The existing React dashboard has purpose-based Shelves, a library, search/Ask, structured notes, entries, capture recovery, and settings backed by the Python application. Contextual Home groups are a new design concept, separate from long-term Shelves. Group membership, group order, Focus workspace, and pins do not yet have production persistence APIs.

Production builds are one nonce-protected HTML file, with system font stacks and no external assets, eval, or route chunks. Prototype code lives separately in prototype/desk-next, uses illustrative fixture data, and must not contact the production API or use production storage keys. No production deployment is authorized.

## Confirmed principles

- Everything should be easy to reach; everything need not be visible simultaneously.
- Home surfaces relevant contexts. Complete extracted knowledge opens after selecting an item.
- Home groups can mix kinds; the person controls organization and stable order.
- Focus contains user-chosen groups; Overview presents the complete group map. Multiple groups can remain open independently.
- Avoid artificial productivity scores, urgency, task-manager conventions, and a permanent third-column drawer.

## Accessibility and evidence

The user requests low cognitive load, keyboard access, responsiveness, and reduced-motion support. The playbook targets WCAG 2.2 AA and 44px hit areas. This is a usability intent, not a clinical ADHD claim.

The user authorized the isolated prototype and subsequently approved saving it as the V5 design checkpoint. [prototype/HOME-V5.md](prototype/HOME-V5.md) preserves its decisions and scope; production integration remains separate. Original A/B1/B2/C HTML, audits and the initial brief are local supplemental artifacts under ignored docs/design/.
