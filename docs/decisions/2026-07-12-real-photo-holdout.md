# Decision log: real-photo holdout — first labeled set (2026-07-12)

Context: the eval-data-sourcing charter (`2026-07-12-eval-data-sourcing.md`)
established that the real-photo holdout (`evals/samples/real/`) is the honest
out-of-sample check that never leaks into tuning, and the directory shipped with
only a README recipe. This work seeds it with the first labeled, runnable cases
and wires it into the harness. What follows are the consequential decisions and
one load-bearing negative result.

## R1 — Freely-licensable pages with a *genuine* highlight do not exist in practice
The core capability we most want to test out-of-sample — "find the marked
passage" — is exactly the one we could not source. The two required properties
are nearly mutually exclusive:
- Pages that carry a **real** highlight are from **in-copyright** books: the best
  candidates found were a CC-BY Flickr photo of a *Kindle screenshot of "The
  Forger's Spell"* (Dolnick, 2008) and CC-BY photos of a **modern Bible
  translation** (NLT — the translation is copyrighted). The photographer's CC-BY
  covers their photo, not the underlying book text; committing such an image to a
  public repo violates the D3 licensing policy regardless.
- **Public-domain** page scans (the only cleanly committable text) are **never
  pre-marked**.

Decision: **do not** commit any in-copyright page image, even one wrapped in a
CC-BY photo. The committed holdout therefore has **no marker/underline modality**.
This is recorded as a finding, not a gap to paper over: the marker/underline
holdout can only come from photos Evan owns (he took them), which the README now
directs him to add over time.

## R2 — Sample from non-literary public-domain scans, not famous novels
Every non-negative and negative case needs a full-page ground-truth transcription
(the CER metric compares the model's full_text to ours). Emitting long verbatim
passages of famous literature trips output content-filters (it killed an earlier
attempt mid-transcription). Decision: build full-text cases from **non-literary**
PD scans — early-1900s gardening/horticulture manuals (Green, *Vegetable
Gardening*, 1896; Bailey, *Manual of Gardening*, 1910) from the Internet Archive.
Their prose transcribes cleanly and is unambiguously public domain. One *Pride and
Prejudice* item is used only for an **illustration plate** whose entire text is
the caption "Mr. Collins proposes." — no literary passage is transcribed.

## R3 — Ground truth = vision transcription cross-checked against IA OCR
Labels are drafted by reading the scan, then reconciled against the source's
Internet Archive OCR (`*_djvu.txt`) to catch transcription slips. IA OCR alone is
too noisy to use raw (it mangles italics and ligatures), so it is a **check**, not
the source. Labels are marked human-verifiable, not gospel, in `labels.json`,
`ATTRIBUTION.md`, and the per-case `description`. A build script
(`build_labels.py`, kept out of the repo) asserts
`full_text[start:end] == expected_highlight` for every positive case.

## R4 — Holdout is scored in complete isolation from the synthetic set
`just eval-real` / `just eval-real-offline` point the existing CLI at
`evals/samples/real/labels.json`. Because the runner derives the cache path from
the dataset's directory, the real set gets its **own** `cache.json` and its own
`evals/reports/real.{html,json}` — synthetic and real numbers can never
cross-contaminate. The committed `cache.json` lets `eval-real-offline` replay in
CI/smoke with zero API cost.

## The seeded set (9 cases) and baseline
Composition (all `difficulty:clean`, since PD scans are the clean floor — no
degraded-photo realism is honestly sourceable yet):
- 6 **instruction** positives (find a described passage on an unmarked page),
  tagged incl. `edge:hyphenated` (a target whose word is hyphenated across a line
  break — exercises hyphen-rejoin) and `edge:multi-sentence`.
- 3 **negatives** (no highlight): a dense text page, a line-engraving plate, and a
  full-page halftone **photograph** — the last two probe hallucination on
  picture-dominated pages.
- 7 of 9 carry a visible page number.

Baseline (online, `service` pipeline, `openai/gpt-5.4`, 2026-07-12), scored
separately from synthetic:

| metric | real holdout | synthetic (for reference) |
|---|---|---|
| Highlight F1 | 100.0% | 97.3% |
| Span IoU | 100.0% | — |
| Span located | 100.0% | — |
| Verbatim | 100.0% | — |
| Full-text CER | 0.028 | — |
| Page-number acc | 100.0% | — |
| Hallucination rate | 0.000 | — |
| p50 latency / $ per case | 4.2 s / $0.015 | — |

**Read the 100% honestly.** The real set is *easier* than synthetic along the
axes it covers: clean flatbed scans, instruction-following, and negatives — no
warped/degraded phone photos and no real highlights. So 100% F1 does **not** mean
the pipeline beats its synthetic score; it means gpt-5.4 handles clean PD scans
and instructions perfectly and, importantly, does not invent highlights on blank
or picture-heavy pages (0/3 hallucinations, including the two photo/engraving
plates). The genuinely hard real-world case — a curled, glare-lit phone photo of
an actual marker highlight — remains **untested** until owned photos are added.
That is the holdout's next and most valuable increment.
