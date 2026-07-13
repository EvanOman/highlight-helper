# Decision log: eval data sourcing (2026-07-12)

Context: after the highlight-quality overhaul (F1 91.4% → 97.3% on synthetic evals), the
next bottleneck is data realism. Three sourcing tracks run in parallel: retain uploaded
images, collect freely-licensed real photos, and augment the synthetic set. Consequential
decisions are recorded here; each track appends its own dated file in this folder.

## D1 — Decision logs are versioned; other docs stay local
`docs/` was fully gitignored ("planning, ideation, notes"). Decision records are operational
history tied to the code, so `.gitignore` now carves out `!docs/decisions/` while plans/notes
remain local-only. Rationale: a decision log that vanishes with a checkout isn't a log.

## D2 — Image retention: filesystem + JSON sidecar, flag default ON
Uploaded images will be persisted at extraction time to `data/uploads/` with a JSON sidecar
(instructions, extraction result, match status, model, sha256) rather than DB blobs.
- Default **ON** (`store_uploaded_images = true`): this is a single-user internal deployment
  behind Tailscale and the whole point is building an eval corpus. The flag exists so any
  future multi-user/production rollout can disable retention.
- Filesystem over DB: images are large, access is batch/offline (eval mining), and the DB
  is precious user data with backup discipline; sidecars make each upload a near-ready eval
  case without schema migrations.
- Retention must never break extraction: storage failures are logged and swallowed.

## D3 — Real-photo licensing policy (public repo)
The repo is public on GitHub, so committed eval images must be Public Domain / CC0 / CC-BY /
CC-BY-SA with attribution recorded in `evals/samples/real/ATTRIBUTION.md`. Unsplash/Pexels
and similar "free" stock licenses are excluded — their terms around redistribution/dataset
compilation are murky. Ground-truth labels drafted by a vision model are marked as such
(human-verifiable, not gospel).

## D4 — Augmentation: extend the existing PIL generator, not Albumentations
Albumentations (the library Evan half-remembered) is the standard tool, but it drags in
opencv-python (~90MB wheel) for what is here ~15° rotations, background compositing, and
placement jitter — all achievable with the PIL machinery the W1 generator already has
(perspective warp, shadow, glare, noise). Decision: build the light augmentation pass on
the existing generator; revisit Albumentations only if augmentation needs grow past what
PIL does cleanly. Augmented cases are ADDITIVE with new ids referencing their parent case —
the original 48 cases are never regenerated, preserving baseline comparability.
