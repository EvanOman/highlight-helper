#!/usr/bin/env python
"""Promote a retained upload into a skeleton eval case under evals/samples/real/.

A retained upload (image + JSON sidecar in ``data/uploads/``) is a NEAR-ready
eval case: the labels were drafted by a vision model and still need human
verification. This script copies the image into ``evals/samples/real/`` and
appends a case to ``evals/samples/real/dataset.json`` with the sidecar's
extraction result prefilled as the expected labels, flagged for verification.

Usage:
    python scripts/promote_upload.py <sidecar-stem-or-path> [--id CASE_ID]

Where <sidecar-stem-or-path> is either:
    - a sidecar stem, e.g. 20260712T140501123456Z-a1b2c3d4
    - a path to the .json sidecar
    - a bare sha8 (picks the most recent sidecar for that image)

The emitted case follows evals.models.EvalCase and is marked
``"needs_verification": true`` — review expected_text before trusting it.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_UPLOADS_DIR = REPO_ROOT / "data" / "uploads"
REAL_SAMPLES_DIR = REPO_ROOT / "evals" / "samples" / "real"
REAL_DATASET = REAL_SAMPLES_DIR / "dataset.json"


def _resolve_sidecar(arg: str, uploads_dir: Path) -> Path:
    """Resolve the CLI argument to a sidecar JSON path."""
    candidate = Path(arg)
    if candidate.suffix == ".json" and candidate.exists():
        return candidate

    stem = candidate.name.removesuffix(".json")
    exact = uploads_dir / f"{stem}.json"
    if exact.exists():
        return exact

    # Treat the argument as a sha8 prefix; pick the most recent matching sidecar.
    matches = sorted(uploads_dir.glob(f"*-{stem}.json"))
    if matches:
        return matches[-1]

    raise FileNotFoundError(f"No sidecar found for '{arg}' in {uploads_dir}")


def _load_dataset() -> dict:
    if REAL_DATASET.exists():
        return json.loads(REAL_DATASET.read_text())
    return {
        "version": "1.0",
        "description": (
            "Real uploaded-page eval cases promoted from retained uploads. "
            "Cases marked needs_verification have model-drafted labels awaiting "
            "human review."
        ),
        "cases": [],
    }


def promote(sidecar_path: Path, case_id: str | None) -> str:
    sidecar = json.loads(sidecar_path.read_text())
    extraction = sidecar.get("extraction", {})

    image_name = sidecar["image"]
    src_image = sidecar_path.parent / image_name
    if not src_image.exists():
        raise FileNotFoundError(f"Sidecar references missing image: {src_image}")

    REAL_SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    dst_image = REAL_SAMPLES_DIR / image_name
    if not dst_image.exists():
        shutil.copy2(src_image, dst_image)

    resolved_id = case_id or f"real_{sidecar_path.stem}"
    case = {
        "id": resolved_id,
        "image_path": f"samples/real/{image_name}",
        "instruction": sidecar.get("instructions", ""),
        # Expected labels are model-drafted — VERIFY before trusting.
        "expected_text": extraction.get("highlight_text") or extraction.get("full_text") or "",
        "expected_page_number": extraction.get("page_number"),
        "category": "real",
        "description": f"Promoted from upload {sidecar_path.name}",
        "needs_verification": True,
        "source_sidecar": sidecar_path.name,
    }

    dataset = _load_dataset()
    dataset["cases"] = [c for c in dataset["cases"] if c.get("id") != resolved_id]
    dataset["cases"].append(case)
    REAL_DATASET.write_text(json.dumps(dataset, indent=2, ensure_ascii=False) + "\n")
    return resolved_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sidecar", help="Sidecar stem, path, or sha8 prefix")
    parser.add_argument("--id", dest="case_id", help="Explicit eval case id")
    parser.add_argument(
        "--uploads-dir",
        default=str(DEFAULT_UPLOADS_DIR),
        help=f"Retained uploads directory (default: {DEFAULT_UPLOADS_DIR})",
    )
    args = parser.parse_args()

    try:
        sidecar_path = _resolve_sidecar(args.sidecar, Path(args.uploads_dir))
        case_id = promote(sidecar_path, args.case_id)
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Promoted {sidecar_path.name} -> case '{case_id}' in {REAL_DATASET}")
    print("  NOTE: labels are model-drafted; verify expected_text before use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
