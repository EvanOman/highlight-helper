# Decision log: image retention (2026-07-12)

Implements track D2 of the eval-data-sourcing plan: every uploaded page photo
becomes a durable, labelled eval-corpus candidate. Records decisions specific to
the retention implementation; see `2026-07-12-eval-data-sourcing.md` D2 for the
foundational choice (filesystem + sidecar, flag default ON).

## R1 — Content-addressed image, per-extraction sidecar (dedupe layout)
The spec named the image `{utc_ts}-{sha256[:8]}.jpg` with a same-stem sidecar,
but also required deduping image bytes across re-extractions. Those conflict: a
ts-prefixed image name writes the same bytes twice when a photo is re-extracted
with new instructions. Resolution:
- **Image** is content-addressed `{sha256[:8]}.jpg` (or original ext for
  non-JPEG), written once — `write-if-absent` dedupes bytes for free.
- **Sidecar** keeps the spec's `{utc_ts}-{sha256[:8]}.json` stem (one per
  extraction; microsecond ts avoids same-second collisions), and records both
  the full `sha256` and the `image` filename so the two stay associated.

Layout under `data/uploads/`:
```
a1b2c3d4.jpg                          # image, content-addressed, written once
20260712T140501123456Z-a1b2c3d4.json  # sidecar for extraction #1 (instructions A)
20260712T142233900001Z-a1b2c3d4.json  # sidecar for extraction #2 (same image, instructions B)
```

## R2 — Sidecar is a near-ready eval case, model-drafted
The sidecar captures timestamp, book_id, original filename, instructions,
sha256, image filename, model used, and the full extraction outcome
(full_text, highlight_text, highlight_start/end, confidence, page_number,
match_status, match_quality, error). It carries `needs_verification: true`:
labels are model-drafted, not ground truth. `match_status`/`match_quality`/
result-carried `error` don't exist on `ExtractedHighlight` on this branch (they
arrive with the honesty tracks); they're read via `getattr(..., None)` so the
sidecar auto-populates once those merge — no future wiring needed.

## R3 — Retention never breaks extraction
All retention I/O runs after extraction and is wrapped so any failure logs a
warning and is swallowed (the request proceeds). It is a synchronous write of an
already-in-memory buffer — no job queue (fire-and-forget from the request's
perspective, but simple). The form route archives on success AND failure so
failed extractions are also mined; `error` is threaded through.

## R4 — Wiring: two call sites on this branch
The archive is injected via FastAPI `Depends(get_upload_archive_service)` into
the JSON API extract endpoint (`app/api/highlights.py`) and the HTML form
extract route (`app/api/views/highlight_views.py`). The spec also named a
"re-extract" route + `image_stash` — those live on the unmerged W4 branch and do
not exist here. The archive DI is a drop-in one-liner for that route when it
merges.

## R5 — Persistence & hygiene
`data/` is already a Docker bind-mount volume (`./data:/app/data` in
docker-compose.yml), so `data/uploads/` persists in the container with no
compose change. `data/uploads/` is gitignored (data, not code). `.gitignore`
also carves out `!docs/decisions/` per eval-sourcing D1 so this log is versioned.
No TTL — this is a corpus; `just uploads-stats` surfaces growth (image count,
sidecar count, total MB). `scripts/promote_upload.py` turns a stored upload into
a skeleton case under `evals/samples/real/`, labels prefilled and flagged for
human verification.
