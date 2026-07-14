# Redesign charter: "Reading Room" (2026-07-13)

Synthesis of two proposals: Fable's aesthetic vision + a GPT-5.5 UX/IA consultation
(numbered IA-*/S-*/C-*/F-*/R-* recommendations; adopted except where noted). This file
is the binding spec for all redesign workers. Behavior, routes, and the honest-extraction
contract do not change — this is a visual + information-architecture redesign.

## Concept

The app is about physical books and the marks we leave in them. The UI is the inside of a
well-loved book plus the desk it sits on: warm paper, quiet ink, and the highlighter stroke
as the single loud voice. **The marker is the brand.** Signature motif: a translucent,
slightly-rotated marker stroke — under headings, behind the active nav item, as the Capture
button treatment, as the editor's selection rendering, and as the extraction loading
animation (a marker sweeping across skeleton lines).

## Design tokens

Typography (self-hosted woff2 in `static/fonts/`, @font-face in input.css, no CDN):
- `font-display`: **Fraunces** (600/700) — headings, book titles, the wordmark
- `font-passage`: **Literata** (400/400i/500) — highlight passages and extracted page text;
  passages must read like book pages
- `font-ui`: **Libre Franklin** (400/500/600) — everything else (labels, buttons, nav, forms)

Color (CSS variables on :root / .dark, mapped into tailwind.config.js as semantic names —
replace the sky-blue `primary` palette entirely):

| Token | Light ("paper") | Dark ("lamplight") |
|---|---|---|
| `--bg` | #FAF6EE | #16130F (warm, never blue-black) |
| `--surface` | #FFFDF7 | #211C15 |
| `--ink` | #1F1B16 | #EAE3D5 |
| `--ink-muted` | #6B6257 | #A89B87 |
| `--line` (hairlines) | #E5DCCB | #383025 |
| `--marker` | #FFD84D | #E2C043 |
| `--marker-stroke` | rgba(255,216,77,.55) | rgba(226,192,67,.38) |
| `--accent` (links, sparing) | #8C3B2E oxblood | #C4674F |

Semantics: green only for saved/synced, red only for destructive, amber for caution — all
re-tinted warm to sit on paper. Texture: near-invisible paper grain (inline SVG noise
data-URI, ≤3% opacity) on `--bg`; raised surfaces are index cards — `--surface`, 1px
`--line` border, low warm shadow.

Motion: editorial restraint. One staggered fade-up on card/list load (40-60ms steps, once);
marker strokes draw in via scaleX origin-left 300ms; everything else 150ms ease-out; full
`prefers-reduced-motion` support. Focus rings: 2px `--marker` outside-offset — visible, on-brand.

## Information architecture (adopted IA-1..7)

- **Mobile: bottom app bar** (fixed, safe-area padded): Books · Highlights · **Capture**
  (center, largest, marker-treated) · Chat · Settings. Top bar shrinks to wordmark +
  dark-mode toggle.
- **Desktop: top bar** with Capture as the visually dominant primary action.
- **Capture flow (F-1..9, R-3):** one thumb-tap from anywhere → `/capture` page: camera-first
  file input (`capture="environment"`), then "Which book?" — starred+recent books first,
  live-filter search, all in ONE form with instructions defaulting to "the highlighted text".
  Tiny JS sets the form action to the existing `/books/{id}/extract` on book selection
  (no-JS fallback: first book preselected). No new extraction backend; one thin GET view
  route for the page itself. Photo is chosen BEFORE book — preserve the reading moment.
- Book detail actions become a compact tray; **Delete Book demotes to overflow** (S-3).
- Coaching renders as a slim contextual prompt row on Books/Highlights, not a hero card (IA-7).
- Metrics demotes behind Settings (S-11); Settings groups into Readwise / Appearance /
  Coaching / Usage / Maintenance (S-10).

## Screen priorities (single highest-leverage fix each, S-1..13)

1. `layouts/base.html` — bottom nav + wordmark; nav must not cover content (R-5:
   bottom padding + `env(safe-area-inset-bottom)` on every page; sticky save bars sit above it).
2. `home.html` — starred/recent-first library, search on top, 2-col mobile covers,
   slim coaching row.
3. `add_highlight.html` + `/capture` — step-state layout (photo → extracting → confirm →
   save); marker-sweep loading state; sticky bottom Save bar; bigger word touch targets;
   marker-real selection rendering (rounded stroke, slight rotation/overlap).
4. `book_detail.html` — action tray, delete to overflow, highlights as a reading river
   (Literata passages, quiet metadata).
5. `all_highlights.html` — search/filter chips on top, denser rows: passage first,
   attribution second; built for 950+ highlights.
6. `chat.html` — restyle wrapper/sidebar ONLY; `ck-app` internals, slots, `api-base`,
   `ck-before-send`, and dark-mode sync are a black box (R-4).
7. `settings.html`, `metrics.html`, `add_book.html`, `add_note.html`, `edit_highlight.html`,
   `error.html`, `partials/pagination.html` — restyle to system; error page gains a
   recovery action pair (Back to Books / Capture).

## Component system (C-1..8)

Buttons (primary/secondary/ghost/destructive/icon, with pressed/loading/disabled),
book cards/rows (skeleton, empty-cover, starred), highlight rows (sync badge states),
extraction status badges (exact→green, normalized/fuzzy→amber, failed→notice not badge —
honest semantics preserved), empty states (one clear next action, usually Capture),
bottom sheets/trays, shared form fields with sticky mobile submit bars.
Implement as Jinja2 macros/partials in `app/templates/components/` where repetition ≥2.

## Hard invariants (R-1, R-2 — breaking these fails review)

- JS hooks unchanged: ids `highlight-editor`, `highlight-text-input`, `save-highlight-btn`,
  `direct-text-editor`, `confidence-badge`, `extract-error`, `manual-section`,
  `match-failed-notice`, `re-extract-form`; classes `highlight-word`, `highlighted`;
  globals `window.__highlightData`, `window.__highlightEditorAPI`. highlight-editor.js
  behavior untouched (visual CSS for selection/handles may change).
- E2E-asserted copy preserved verbatim: "Books", "Highlights", "Add Highlight",
  "Extract from Image", "Enter Manually", "Add Manually", "Save Highlight",
  "Confidence: high", "New Chat", the match-failed notice, and the "…read the page…"
  extraction-failed message. Any deliberate copy change requires updating the test in the
  same commit and flagging it in the handoff report.
- Server behavior: no route removals or renames; `/capture` is additive. Honest-extraction
  states exactly as today (failed match = nothing preselected, Save gated; empty full_text =
  explicit error with instructions preserved; re-extract token flow).
- Dark-mode `class` strategy stays; both themes shipped in every phase.
- Fonts self-hosted; no external network calls from pages.
- Gates for every phase: `just fc` and `just test-e2e` green (chat phase also `just selftest`).

## Phasing

1. **Foundation**: fonts, tokens, tailwind.config, input.css, base layout + both navs,
   button/card/badge components, error page. Everything else may look transitional but must
   not break.
2. **Surfaces** (parallel, disjoint): (a) library home + book detail + add_book;
   (b) capture + add_highlight + edit_highlight + add_note; (c) all_highlights + settings +
   metrics + pagination; (d) chat wrapper.
3. **Polish**: cross-surface consistency sweep, motion, empty states, screenshot review in
   both themes at 390px and 1280px.

## Status: shipped 2026-07-14

Deployed to production after phases 1-3 + polish; all gates green (492 unit/integration,
27 E2E incl. deliberate `# redesign:` test updates, selftest). Chatkit gained a themable
user-bubble gradient (`--ck-accent-2`, chatkit commit 9040f49, re-vendored). Known
leftovers, deliberately unshipped: redundant uppercase eyebrows on edit_highlight.html /
add_book.html (same pattern as the fixed add_highlight one); "PHASE 1" appears in both
the pill and the card eyebrow on add_highlight. Cosmetic only.
