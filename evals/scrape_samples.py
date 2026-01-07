#!/usr/bin/env python3
"""Script to download sample book page images for evaluation."""

import json
import urllib.request
from pathlib import Path

# Sample book page images from Internet Archive / public domain sources
# These are direct links to public domain book page scans
SAMPLE_IMAGES = [
    {
        "id": "sample_01",
        "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8d/Erta_ale_5-Trimmed.jpg/800px-Erta_ale_5-Trimmed.jpg",
        "filename": "sample_01.jpg",
        "description": "Test image - will be replaced with actual book page",
    },
]

# For offline testing, we'll create synthetic test images with known text
# These will be simple text-on-white images we can create programmatically


def create_synthetic_samples(output_dir: Path) -> list[dict]:
    """Create synthetic test images with known text for offline testing."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Pillow not installed, skipping synthetic image generation")
        return []

    samples = []
    output_dir.mkdir(parents=True, exist_ok=True)

    # Sample texts for testing
    test_cases = [
        {
            "id": "synthetic_01",
            "text": "The only way to do great work is to love what you do.",
            "instruction": "Extract all the text",
            "category": "simple",
        },
        {
            "id": "synthetic_02",
            "text": "In the beginning, there was nothing. Then there was everything.",
            "instruction": "Extract the text starting with 'In the beginning'",
            "category": "instruction-based",
        },
        {
            "id": "synthetic_03",
            "text": "Page 42\n\nTo be or not to be, that is the question.",
            "instruction": "Extract the quote",
            "expected_page": "42",
            "category": "with-page-number",
        },
        {
            "id": "synthetic_04",
            "text": "The quick brown fox jumps over the lazy dog.",
            "instruction": "Get the sentence about the fox",
            "category": "instruction-based",
        },
        {
            "id": "synthetic_05",
            "text": (
                "First paragraph here.\n\n"
                "Second paragraph with more content.\n\n"
                "Third paragraph at the end."
            ),
            "instruction": "Extract the second paragraph",
            "expected_text": "Second paragraph with more content.",
            "category": "instruction-based",
        },
    ]

    for case in test_cases:
        # Create a simple white image with text
        img = Image.new("RGB", (800, 400), color="white")
        draw = ImageDraw.Draw(img)

        # Use default font
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", 24)
        except OSError:
            font = ImageFont.load_default()

        # Draw the text
        text = case["text"]
        draw.text((50, 50), text, fill="black", font=font)

        # Save the image
        filename = f"{case['id']}.png"
        img_path = output_dir / filename
        img.save(img_path)

        # Determine expected text (might be different from full text for instruction-based)
        expected = case.get("expected_text", case["text"].replace("\n\n", " ").replace("\n", " "))

        samples.append(
            {
                "id": case["id"],
                "image_path": f"samples/{filename}",
                "instruction": case["instruction"],
                "expected_text": expected,
                "expected_page_number": case.get("expected_page"),
                "category": case["category"],
                "description": f"Synthetic test: {case['instruction']}",
            }
        )

        print(f"Created {filename}")

    return samples


def download_samples(output_dir: Path) -> list[dict]:
    """Download sample images from the web."""
    output_dir.mkdir(parents=True, exist_ok=True)
    samples = []

    for sample in SAMPLE_IMAGES:
        filepath = output_dir / sample["filename"]
        if not filepath.exists():
            print(f"Downloading {sample['filename']}...")
            try:
                urllib.request.urlretrieve(sample["url"], filepath)
            except Exception as e:
                print(f"  Failed: {e}")
                continue
        samples.append(sample)

    return samples


def create_dataset(samples: list[dict], output_path: Path) -> None:
    """Create the dataset JSON file."""
    dataset = {
        "version": "1.0",
        "description": "Evaluation dataset for highlight extraction",
        "cases": samples,
    }

    with open(output_path, "w") as f:
        json.dump(dataset, f, indent=2)

    print(f"\nCreated dataset with {len(samples)} cases at {output_path}")


def main():
    """Generate sample images and dataset."""
    evals_dir = Path(__file__).parent
    samples_dir = evals_dir / "samples"

    print("Creating synthetic test samples...")
    samples = create_synthetic_samples(samples_dir)

    print(f"\nTotal samples: {len(samples)}")

    # Create the dataset file
    dataset_path = samples_dir / "dataset.json"
    create_dataset(samples, dataset_path)

    # Create a cache file with mock results for offline testing
    cache = {}
    for sample in samples:
        cache_key = f"{sample['id']}:{sample['instruction']}"
        cache[cache_key] = {
            "text": sample["expected_text"],
            "page_number": sample.get("expected_page_number"),
            "confidence": "high",
            "latency_ms": 100.0,
        }

    cache_path = samples_dir / "cache.json"
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=2)
    print(f"Created cache file at {cache_path}")


if __name__ == "__main__":
    main()
