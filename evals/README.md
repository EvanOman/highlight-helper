# Highlight Extraction Evaluation Framework

This framework measures the quality and accuracy of the AI-powered highlight extraction feature.

## Quick Start

```bash
# Run evals offline (no API calls, uses cached results)
python -m evals.cli --offline

# Run evals online (calls OpenAI API - requires OPENAI_API_KEY)
python -m evals.cli

# Verbose output
python -m evals.cli --offline --verbose
```

## Features

- **Online/Offline modes**: Run without API calls using cached results
- **HTML reports**: Visual summary of results at `evals/reports/latest.html`
- **Standard exit codes**: Exit 0 on pass, exit 1 on fail (for CI integration)
- **Configurable threshold**: Default 80% pass rate required

## Metrics

| Metric | Description |
|--------|-------------|
| **Exact Match** | Text matches expected exactly (case-insensitive) |
| **Char Accuracy** | Character-level accuracy using Levenshtein distance |
| **Confidence** | Model's self-reported confidence (high/medium/low) |
| **Latency** | Time to extract text from image |

A test case passes if it has either an exact match OR char accuracy >= 90%.

## Adding New Test Cases

### 1. Add image to `samples/`

Place your test image in the `evals/samples/` directory.

### 2. Update `dataset.json`

Add a new entry to `evals/samples/dataset.json`:

```json
{
  "id": "my_test_01",
  "image_path": "samples/my_image.png",
  "instruction": "Extract the highlighted text",
  "expected_text": "The exact text you expect",
  "expected_page_number": "42",
  "category": "highlighted",
  "description": "Test case description"
}
```

### 3. Run online to populate cache

```bash
python -m evals.cli --verbose
```

This will call the API and save results to `cache.json` for future offline runs.

## Eval Categories

| Category | Description |
|----------|-------------|
| `simple` | Basic text extraction |
| `highlighted` | Visually highlighted/underlined text |
| `instruction-based` | Natural language instructions (e.g., "get the first paragraph") |
| `with-page-number` | Tests page number detection |
| `edge-case` | Poor lighting, handwriting, multiple columns |

## Generating Synthetic Samples

To regenerate synthetic test images:

```bash
python evals/scrape_samples.py
```

## CLI Options

```
python -m evals.cli [OPTIONS]

Options:
  --dataset PATH       Path to dataset JSON (default: evals/samples/dataset.json)
  --offline            Use cached results, no API calls
  --cache PATH         Path to cache file
  --report-path PATH   Where to write HTML report (default: evals/reports/latest.html)
  --no-report          Skip HTML report generation
  -v, --verbose        Print progress for each test case
  --threshold FLOAT    Pass rate threshold % (default: 80)
```

## CI Integration

Add to your GitHub Actions workflow:

```yaml
- name: Run evals (offline)
  run: python -m evals.cli --offline --threshold 80
```

For online evals (requires `OPENAI_API_KEY` secret):

```yaml
- name: Run evals (online)
  run: python -m evals.cli --threshold 80
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```
