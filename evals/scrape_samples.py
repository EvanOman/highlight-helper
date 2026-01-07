#!/usr/bin/env python3
"""Script to generate synthetic sample images for evaluation."""

import json
from pathlib import Path


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


def create_dataset(samples: list[dict], output_path: Path) -> None:
    """Create the dataset JSON file."""
    dataset = {
        "version": "1.0",
        "description": "Evaluation dataset for highlight extraction",
        "cases": samples,
    }

    with open(output_path, "w", encoding="utf-8") as f:
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
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)
    print(f"Created cache file at {cache_path}")


if __name__ == "__main__":
    main()
