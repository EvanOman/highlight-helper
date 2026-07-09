# Real-photo holdout set

This directory holds **labeled real phone photos** of highlighted book pages —
the out-of-sample set. The synthetic dataset (`../dataset.json`) is generated and
can be over-fit; these real photos are the honest check that never leaks into
tuning. They are scored **separately** from the synthetic set.

The app discards uploaded photos after extraction (by design, for privacy), so
this set has to be built by hand over time. Drop images here as you take them.

## How to add a case

1. Photograph a real book page with a visible highlight (marker, underline, or a
   pen bracket), or a clean page for a negative case. Save it here, e.g.
   `real/0001.jpg`.
2. Transcribe the ground truth **by hand** and add a record to `labels.json` in
   this directory (create it if missing) with the same schema as the synthetic
   dataset:

   ```json
   {
     "version": "real-1.0",
     "description": "Hand-labeled real phone photos (holdout).",
     "cases": [
       {
         "id": "real-0001",
         "image_path": "real/0001.jpg",
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

   Compute `expected_start` / `expected_end` as the character offsets of
   `expected_highlight` within `full_text` (they must satisfy
   `full_text[expected_start:expected_end] == expected_highlight`). For negative
   cases set `expected_highlight` to `""`, the offsets to `0`, and
   `is_negative` to `true`.

## Running the holdout

Point the CLI at this label file (scored on its own, separate from synthetic):

```bash
uv run python -m evals.cli --dataset evals/samples/real/labels.json \
  --report-path evals/reports/real.html --json-out evals/reports/real.json
```

Keep the image resolution close to what the app actually receives (a normal
phone photo), so the numbers reflect production conditions.
