# Decision log: eval data augmentation (2026-07-12)

Track 3 of the eval-data-sourcing effort (see `2026-07-12-eval-data-sourcing.md`,
D4). Goal: measure how much of the 97.3% synthetic F1 is *clean-render flattery*
by adding harder, phone-photo-like variants that keep the text ground truth
intact. New module `evals/augment_dataset.py`; unit tests in
`tests/unit/test_evals_augment.py`. Run: `evals/reports/augmented-2026-07-12.{html,json}`.

## A1 — Confirmed D4: extend the PIL generator, no Albumentations/opencv
Everything the brief asked for — background compositing, ±15° rotation, stronger
keystone, colour temperature, uneven exposure, vignette, sensor noise, motion
blur — is a few dozen lines of PIL + numpy. Perspective is a 4-point projective
warp: solve the 8 coefficients with `numpy.linalg.solve` and hand them to
`Image.transform(PERSPECTIVE)`. opencv/Albumentations would add a ~90 MB wheel for
zero capability we lack here. D4 stands; not revisited.

## A2 — numpy promoted to a direct dependency
`augment_dataset` imports numpy directly (perspective solve, seeded noise, gradient
masks). numpy was already resolved (2.4.1, transitively via dspy/optuna), so
declaring `numpy>=1.26.0` in `[project].dependencies` changed nothing in the lock
but removes a latent break if dspy ever drops it. Consistent with pillow, also an
eval-tooling dep living in main deps.

## A3 — Seeded numpy noise instead of `Image.effect_noise`
`PIL.Image.effect_noise` draws from an internal RNG that `random.seed` cannot
control, so it is **not** byte-deterministic. Since the brief requires
determinism (and there's a unit test for it), the augmenter regenerates grain
with `numpy.random.default_rng(seed)` for both sensor noise and background
texture. The W1 generator (unchanged here) uses `effect_noise`, so its committed
PNGs are not reproducible — noted, not fixed, to preserve the frozen 48.

## A4 — Additive schema: `parent_id` + `augmentation` tag, originals byte-frozen
Augmented cases inherit every ground-truth field and category label from the
parent verbatim, get id `{parent_id}-aug-{level}`, and add two fields:
`parent_id` and `augmentation` (easy|medium|hard). `EvalCase.tags` emits
`augmentation:{level}` **in addition to** the parent's modality/difficulty/
density/edge tags, so rollups slice both ways. `dataset.json` is rewritten by
appending only — the 48 original case dicts are never routed through a dataclass,
so they stay byte-identical (verified: `git diff` is +540/−0). The 48 PNGs are
untouched; augmented PNGs are named `*-aug-*.png` and cleared/regenerated in
isolation.

## A5 — Geometry invariant: whole page always inside the frame
The page is scaled to 70–95% of a 1280×1600 frame, keystoned, rotated (±5/±10/±15°
by level), and jittered — then a deterministic shrink-to-fit step scales toward
the centroid and translates so all four corners sit ≥24 px inside every edge. This
guarantees no glyph is ever clipped by the frame (unit-tested over 900 seeds).
Backgrounds sit **behind** the page and all photometrics are global/translucent,
so nothing occludes text — occlusion would change the effective ground truth.

## A6 — Parent sampling: 10 clean-base parents × 3 levels = 30 cases
Chose 10 parents, all *clean*-difficulty bases so the augmentation is the only
degradation stacked on (an honest augmentation-only delta, not degraded²):
marker×2 short, underline short, instruction, negative, marker+underline dense,
and the hyphenated / repeated-phrase / multi-sentence edges. Each gets easy,
medium, hard → 30 cases, balanced 10/10/10 for a clean per-difficulty rollup.

## Findings — the score is *mostly* not flattery, but the tail is real
Online run, `service-v2` (DSPy cache off), openai/gpt-5.4, **$0.41, 0 errors**:

| slice     | F1     | IoU    | span located | verbatim | CER   |
|-----------|--------|--------|--------------|----------|-------|
| baseline (48, un-aug) | 97.3% | 98.1% | 100% | 100%  | 0.048 |
| aug easy   | 99.3% | 99.9% | 100%        | 100.0%   | 0.045 |
| aug medium | 99.0% | 99.8% | 100%        | 100.0%   | 0.045 |
| aug hard   | 92.5% | 92.7% | 100%        | 77.8%    | 0.045 |

- **Easy/medium match or beat the 97.3% baseline.** Background compositing,
  moderate tilt/keystone, colour cast and mild noise cost the pipeline almost
  nothing — gpt-5.4 reads a tilted page on a desk about as well as a square scan.
  So the headline number is *not* primarily clean-render flattery.
- **Hard bites.** ±15° rotation + strong keystone + glare + motion blur + heavy
  vignette drops F1 to 92.5% and, more tellingly, **verbatim to 77.8%**: two hard
  cases (dense marker, multi-sentence) fell to `fuzzy` matches — the OCR drifted
  enough that the extracted text is no longer an exact/normalized page substring.
- **The hyphenation edge collapses under hard augmentation:**
  `cartography-hyphen-clean-aug-hard` scored **F1 0.50 / IoU 0.37** (worst case),
  dragging `edge:hyphenated` to 83% F1. Hyphenated line-break spans are the
  fragile intersection of span-localization and image distortion — the clearest
  place to harden next.
- **No regressions elsewhere:** span-located stayed 100% (the model always found
  *something* plausible), page-number accuracy 100%, and all 3 augmented negatives
  stayed clean (0% hallucination) even under hard distortion. Full-text CER held
  ~0.045 across all levels, so failures are span-**localization**, not OCR.
