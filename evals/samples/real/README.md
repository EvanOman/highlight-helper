# Real-photo holdout set

This directory holds the **out-of-sample holdout** — labeled real book/manual
pages, scored **separately** from the synthetic set (`../dataset.json`), which is
generated and can be over-fit. The holdout is the honest check that never leaks
into tuning.

## What's here now (seeded set)

`labels.json` ships **9 labeled cases** built from public-domain Internet Archive
page scans (early-1900s gardening manuals + one *Pride and Prejudice* plate). They
cover the **instruction** modality (find the passage the user describes on an
unmarked page) and **negative** cases (no highlight → must return nothing,
including two picture-dominated plates). Licensing for every image is tracked in
`ATTRIBUTION.md`; labels are vision transcriptions cross-checked against Internet
Archive OCR (human-verifiable drafts, not gospel).

There are **no marker/underline cases** here: freely-licensable pages with a real
highlight don't exist (highlighted pages are copyrighted; PD scans are unmarked).
The realism gap — genuine phone photos with real highlights, curvature, glare —
is what your own photos fill.

The app discards uploaded photos after extraction (by design, for privacy), so
that part of the set has to be built by hand over time. Drop images here as you
take them.

## How to add a case

1. Photograph a real book page with a visible highlight (marker, underline, or a
   pen bracket), or a clean page for a negative case. Save it here, e.g.
   `0042.jpg`.
2. Transcribe the ground truth **by hand** and add a record to `labels.json` in
   this directory (create it if missing) with the same schema as the synthetic
   dataset:

   ```json
   {
     "version": "real-1.0",
     "description": "Hand-labeled real phone photos (holdout).",
     "cases": [
       {
         "id": "real-0042",
         "image_path": "0042.jpg",
         "instruction": "Extract the highlighted sentence.",
         "full_text": "<the full, faithful page text, verbatim>",
         "expected_highlight": "<the exact highlighted substring of full_text>",
         "expected_start": 0,
         "expected_end": 0,
         "expected_page_number": "84",
         "modality": "marker",
         "difficulty": "degraded",
         "density": "dense",
         "edge_case": null,
         "is_negative": false
       }
     ]
   }
   ```

   `image_path` is resolved **relative to this `labels.json` file**, so use the
   bare filename (`0042.jpg`), not `real/0042.jpg`.

   Compute `expected_start` / `expected_end` as the character offsets of
   `expected_highlight` within `full_text` (they must satisfy
   `full_text[expected_start:expected_end] == expected_highlight`). For negative
   cases set `expected_highlight` to `""`, the offsets to `0`, and
   `is_negative` to `true`.

## Running the holdout

```bash
just eval-real          # online: real API, writes evals/reports/real.{html,json}
just eval-real-offline  # replay the committed cache.json (no API cost)
```

Both target this label file only, with their own `cache.json` in this directory,
so the real numbers are **never** mixed into the synthetic aggregates. Under the
hood:

```bash
uv run python -m evals.cli --dataset evals/samples/real/labels.json \
  --report-path evals/reports/real.html --json-out evals/reports/real.json
```

Keep the image resolution close to what the app actually receives (a normal
phone photo), so the numbers reflect production conditions.
