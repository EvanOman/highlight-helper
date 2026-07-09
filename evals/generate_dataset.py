#!/usr/bin/env python3
"""Generate a synthetic-realistic highlight-extraction dataset.

Renders book-like pages from ORIGINAL neutral prose (see ``passages.py``) with a
justified serif body, running header, and page number, then composites *actual*
visual highlights (translucent marker strokes, pen underlines, margin brackets)
over a known character span, and finally applies photo-realism degradations
(quad warp, rotation, brightness gradient, blur, noise, glare, low light).

Ground truth is known by construction: the full page text, the exact highlight
text, its character span, the page number, and category labels. Everything is
seeded per case, so regeneration is deterministic.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from zlib import crc32

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from evals.passages import PASSAGES, Passage

# --- Page geometry ---------------------------------------------------------
PAGE_W = 1000
PAGE_H = 1400
MARGIN_L = 115
MARGIN_R = 115
MARGIN_TOP = 170
TEXT_W = PAGE_W - MARGIN_L - MARGIN_R
PAPER = (246, 243, 236)
INK = (28, 26, 24)

FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
FONT_ITALIC = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf"


@dataclass
class Word:
    """One logical word with its char span in full_text and rendered fragments.

    A hyphenated word has two fragment boxes on two lines but a single char span.
    """

    text: str
    start: int
    end: int
    para: int
    frags: list[tuple[float, float, float, float]] = field(default_factory=list)
    hyphenated: bool = False


def _build_text(paragraphs: list[str]) -> tuple[str, list[Word]]:
    """Join paragraphs into full_text and record each word's char span.

    Paragraphs are separated by a blank line; words by a single space. Each
    :class:`Word` remembers its half-open ``[start, end)`` char span into the
    returned ``full_text``.
    """
    parts: list[str] = []
    words: list[Word] = []
    offset = 0
    for pi, para in enumerate(paragraphs):
        tokens = para.split()
        for wi, tok in enumerate(tokens):
            start = offset
            parts.append(tok)
            offset += len(tok)
            words.append(Word(text=tok, start=start, end=offset, para=pi))
            if wi < len(tokens) - 1:
                parts.append(" ")
                offset += 1
        if pi < len(paragraphs) - 1:
            parts.append("\n\n")
            offset += 2
    return "".join(parts), words


def _best_split(word: str, remaining: float, font: ImageFont.FreeTypeFont) -> int | None:
    """Largest split index whose ``prefix-`` fits in ``remaining`` px (prefix>=3, suffix>=2)."""
    for split in range(len(word) - 2, 2, -1):
        if font.getlength(word[:split] + "-") <= remaining:
            return split
    return None


def _layout_and_draw(
    draw: ImageDraw.ImageDraw,
    words: list[Word],
    font: ImageFont.FreeTypeFont,
    text_w: int,
    glyph_h: float,
    line_height: float,
) -> None:
    """Word-wrap ``words`` into justified lines, drawing them and filling frag boxes."""
    space_w = font.getlength(" ")
    n_paras = (max(w.para for w in words) + 1) if words else 0
    line_index = 0

    def flush(line_frags: list[tuple[Word, str]], justify: bool) -> None:
        nonlocal line_index
        if not line_frags:
            return
        widths = [font.getlength(t) for _, t in line_frags]
        total_w = sum(widths)
        n = len(line_frags)
        y0 = MARGIN_TOP + line_index * line_height
        gap = (text_w - total_w) / (n - 1) if (justify and n > 1) else space_w
        x = float(MARGIN_L)
        for (w, t), wd in zip(line_frags, widths, strict=True):
            draw.text((x, y0), t, fill=INK, font=font)
            w.frags.append((x, y0, x + wd, y0 + glyph_h))
            x += wd + gap
        line_index += 1

    for pi in range(n_paras):
        para_words = [w for w in words if w.para == pi]
        line_frags: list[tuple[Word, str]] = []
        cur_w = 0.0
        for w in para_words:
            wmeasure = font.getlength(w.text)
            gap = space_w if line_frags else 0.0
            if cur_w + gap + wmeasure <= text_w:
                line_frags.append((w, w.text))
                cur_w += gap + wmeasure
                continue
            remaining = text_w - cur_w - (space_w if line_frags else 0.0)
            split = (
                _best_split(w.text, remaining, font) if (line_frags and len(w.text) >= 8) else None
            )
            if split is not None:
                prefix = w.text[:split] + "-"
                line_frags.append((w, prefix))
                w.hyphenated = True
                flush(line_frags, justify=True)
                line_frags = [(w, w.text[split:])]
                cur_w = font.getlength(w.text[split:])
            else:
                flush(line_frags, justify=True)
                line_frags = [(w, w.text)]
                cur_w = wmeasure
        flush(line_frags, justify=False)


def render_page(
    passage: Passage,
    font_size: int,
    page_number: str | None,
) -> tuple[Image.Image, str, list[Word]]:
    """Render a clean page and return (RGBA image, full_text, words with boxes)."""
    full_text, words = _build_text(passage.paragraphs)
    img = Image.new("RGBA", (PAGE_W, PAGE_H), (*PAPER, 255))
    draw = ImageDraw.Draw(img)

    body = ImageFont.truetype(FONT_REGULAR, font_size)
    header_font = ImageFont.truetype(FONT_ITALIC, 22)
    page_font = ImageFont.truetype(FONT_REGULAR, 22)

    ascent, descent = body.getmetrics()
    glyph_h = ascent + descent
    line_height = glyph_h * 1.42

    # Running header, centered, with a hairline rule beneath it.
    hx = (PAGE_W - draw.textlength(passage.title, font=header_font)) / 2
    draw.text((hx, 96), passage.title, fill=(90, 84, 76), font=header_font)
    draw.line([(MARGIN_L, 138), (PAGE_W - MARGIN_R, 138)], fill=(170, 160, 148), width=1)

    _layout_and_draw(draw, words, body, TEXT_W, glyph_h, line_height)

    if page_number is not None:
        px = (PAGE_W - draw.textlength(page_number, font=page_font)) / 2
        draw.text((px, PAGE_H - 96), page_number, fill=(90, 84, 76), font=page_font)

    return img, full_text, words


# --- Highlight compositing -------------------------------------------------
def _frag_boxes(words: list[Word], start: int, end: int) -> list[tuple[float, float, float, float]]:
    """All rendered fragment boxes for words overlapping the char span."""
    boxes: list[tuple[float, float, float, float]] = []
    for w in words:
        if w.start < end and w.end > start:
            boxes.extend(w.frags)
    return boxes


def composite_marker(img: Image.Image, boxes: list, rng: random.Random) -> None:
    """Translucent yellow marker strokes with alpha and edge jitter over each box."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for x0, y0, x1, y1 in boxes:
        top = y0 - rng.uniform(1, 4)
        bot = y1 + rng.uniform(1, 5)
        for _ in range(2):
            jt = top + rng.uniform(-2.0, 2.0)
            jb = bot + rng.uniform(-2.0, 2.0)
            ex0 = x0 - rng.uniform(1, 6)
            ex1 = x1 + rng.uniform(1, 9)
            color = (255, rng.randint(212, 236), rng.randint(20, 60), rng.randint(58, 92))
            od.rounded_rectangle([ex0, jt, ex1, jb], radius=5, fill=color)
    overlay = overlay.filter(ImageFilter.GaussianBlur(0.6))
    img.alpha_composite(overlay)


def composite_underline(img: Image.Image, boxes: list, rng: random.Random) -> None:
    """A slightly wavy pen underline beneath each box."""
    d = ImageDraw.Draw(img)
    for x0, _y0, x1, y1 in boxes:
        yb = y1 + rng.uniform(0, 3)
        color = (rng.randint(10, 45), rng.randint(20, 55), rng.randint(85, 140))
        steps = max(2, int((x1 - x0) // 16))
        phase = rng.uniform(0, math.pi)
        pts = [
            (
                x0 + (x1 - x0) * (i / steps),
                yb + math.sin((i / steps) * math.pi * 2 + phase) * 1.3,
            )
            for i in range(steps + 1)
        ]
        d.line(pts, fill=color, width=3, joint="curve")


def composite_bracket(img: Image.Image, boxes: list, rng: random.Random) -> None:
    """A margin bracket spanning the highlighted lines."""
    d = ImageDraw.Draw(img)
    top = min(b[1] for b in boxes) - 3
    bot = max(b[3] for b in boxes) + 3
    xm = MARGIN_L - rng.uniform(20, 34)
    color = (rng.randint(25, 55), rng.randint(25, 55), rng.randint(35, 70))
    d.line([(xm, top), (xm, bot)], fill=color, width=3)
    d.line([(xm, top), (xm + 13, top)], fill=color, width=3)
    d.line([(xm, bot), (xm + 13, bot)], fill=color, width=3)


# --- Photo-realism degradations -------------------------------------------
def _small_gradient(size: tuple[int, int], rng: random.Random, dark: float) -> Image.Image:
    """A low-res radial darkening mask upscaled to full size (cheap vignette/shadow)."""
    w, h = size
    sw, sh = 48, max(1, int(48 * h / w))
    cx, cy = rng.uniform(0.2, 0.8), rng.uniform(0.2, 0.8)
    data: list[int] = []
    for y in range(sh):
        for x in range(sw):
            dx, dy = (x / sw - cx), (y / sh - cy)
            d = math.hypot(dx, dy) / 1.15
            v = 1.0 - (1.0 - dark) * min(1.0, d)
            data.append(int(max(0, min(255, v * 255))))
    small = Image.new("L", (sw, sh))
    small.putdata(data)
    return small.resize(size, Image.Resampling.BILINEAR)


def _brightness_gradient(img: Image.Image, rng: random.Random, dark: float) -> Image.Image:
    mask = _small_gradient(img.size, rng, dark)
    grad = Image.merge("RGB", (mask, mask, mask))
    return ImageChops.multiply(img.convert("RGB"), grad)


def _add_glare(img: Image.Image, rng: random.Random) -> Image.Image:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    w, h = img.size
    cx, cy = rng.uniform(0.2, 0.8) * w, rng.uniform(0.12, 0.6) * h
    rx, ry = rng.uniform(0.14, 0.3) * w, rng.uniform(0.09, 0.19) * h
    d.ellipse(
        [cx - rx, cy - ry, cx + rx, cy + ry],
        fill=(255, 255, 246, rng.randint(55, 105)),
    )
    overlay = overlay.filter(ImageFilter.GaussianBlur(28))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _add_noise(img: Image.Image, rng: random.Random, sigma: float) -> Image.Image:
    noise = Image.effect_noise(img.size, sigma)
    noise_rgb = Image.merge("RGB", (noise, noise, noise))
    return Image.blend(img.convert("RGB"), noise_rgb, alpha=0.11)


def _rotate(img: Image.Image, rng: random.Random, max_deg: float) -> Image.Image:
    angle = rng.uniform(-max_deg, max_deg)
    return img.convert("RGB").rotate(
        angle, resample=Image.Resampling.BILINEAR, expand=False, fillcolor=PAPER
    )


def _warp_quad(img: Image.Image, rng: random.Random, m: float) -> Image.Image:
    w, h = img.size
    quad = (
        rng.uniform(0, w * m),
        rng.uniform(0, h * m),  # upper-left
        rng.uniform(0, w * m),
        h - rng.uniform(0, h * m),  # lower-left
        w - rng.uniform(0, w * m),
        h - rng.uniform(0, h * m),  # lower-right
        w - rng.uniform(0, w * m),
        rng.uniform(0, h * m),  # upper-right
    )
    return img.convert("RGB").transform(
        (w, h), Image.Transform.QUAD, quad, Image.Resampling.BILINEAR, fillcolor=PAPER
    )


def degrade(img: Image.Image, difficulty: str, rng: random.Random) -> Image.Image:
    """Apply the degradation stack for a difficulty level; ground truth is unaffected."""
    out = img.convert("RGB")
    if difficulty == "clean":
        out = _rotate(out, rng, 0.5)
    elif difficulty == "warped":
        out = _warp_quad(out, rng, 0.05)
        out = _rotate(out, rng, 2.4)
        out = _brightness_gradient(out, rng, 0.78)
    elif difficulty == "degraded":
        out = _brightness_gradient(out, rng, 0.6)
        out = _add_glare(out, rng)
        out = out.filter(ImageFilter.GaussianBlur(rng.uniform(0.8, 1.5)))
        out = _add_noise(out, rng, rng.uniform(7, 14))
        out = _rotate(out, rng, 1.6)
        out = ImageEnhance.Brightness(out).enhance(rng.uniform(0.62, 0.82))
    return out


# --- Case specs ------------------------------------------------------------
@dataclass
class CaseSpec:
    id: str
    passage: str
    instruction: str
    modality: str  # marker | underline | instruction | none
    difficulty: str  # clean | warped | degraded
    density: str  # short | dense
    highlight: str | None = None  # verbatim phrase; None for instruction-only/negative
    edge_case: str | None = None
    is_negative: bool = False
    page_number: str | None = None
    add_bracket: bool = False
    hyphen_target: bool = False  # locate a hyphenated word and highlight around it


def _seed(case_id: str) -> int:
    return crc32(case_id.encode()) & 0xFFFFFFFF


def _hyphen_span(words: list[Word]) -> tuple[int, int, str, str] | None:
    """Find a hyphenated word and return (start, end, phrase, hyphenated_word)
    for a short highlight of it plus one neighbour on each side."""
    for i, w in enumerate(words):
        if not w.hyphenated:
            continue
        lo = words[i - 1] if i > 0 and words[i - 1].para == w.para else w
        hi = words[i + 1] if i + 1 < len(words) and words[i + 1].para == w.para else w
        return lo.start, hi.end, "", w.text
    return None


CASE_SPECS: list[CaseSpec] = []


def _register_core() -> None:
    """Core positive cases: a chosen highlight per passage across modality x difficulty."""
    # (passage, highlight phrase, instruction, page number)
    cores = [
        (
            "sailing",
            "A good sailor learns to read the water for the darker ruffled patches that mark a coming gust",
            "Extract the highlighted sentence.",
            "23",
        ),
        (
            "astronomy",
            "it can resolve the rings of a distant planet into a clean bright ellipse",
            "Extract the highlighted text.",
            "58",
        ),
        (
            "beekeeping",
            "Most of what a beginner does to a hive is a disturbance",
            "Extract the highlighted phrase.",
            "104",
        ),
        (
            "tides",
            "The tide is the ocean leaning, ever so slightly, toward the moon.",
            "Extract the highlighted sentence.",
            "12",
        ),
        (
            "bread",
            "There comes a moment when the dough stops fighting and turns supple",
            "Extract the highlighted text.",
            "77",
        ),
    ]
    variants = [
        ("marker", "clean"),
        ("marker", "warped"),
        ("marker", "degraded"),
        ("underline", "clean"),
        ("underline", "degraded"),
    ]
    for passage, phrase, instruction, page in cores:
        for modality, difficulty in variants:
            cid = f"{passage}-{modality}-{difficulty}"
            CASE_SPECS.append(
                CaseSpec(
                    id=cid,
                    passage=passage,
                    instruction=instruction,
                    modality=modality,
                    difficulty=difficulty,
                    density="short",
                    highlight=phrase,
                    page_number=page,
                    add_bracket=(modality == "marker" and difficulty == "clean"),
                )
            )


def _register_instruction_only() -> None:
    specs = [
        (
            "gardening",
            "Extract the sentence that describes what compost is.",
            "Compost is the garden's memory.",
            "clean",
            "31",
        ),
        (
            "gardening",
            "Find the sentence about which tool never wears out.",
            "Patience is the only tool that never wears out.",
            "warped",
            "33",
        ),
        (
            "astronomy",
            "Extract the sentence stating the first rule of the hobby.",
            "The first rule of the hobby is simply to find the dark.",
            "clean",
            "60",
        ),
        (
            "sailing",
            "Give me the sentence that defines trimming as the quiet craft.",
            "Trimming is the quiet craft at the center of it all.",
            "clean",
            "24",
        ),
        (
            "bread",
            "Extract the sentence about what the oven does.",
            "The oven finishes what the hands began.",
            "warped",
            "78",
        ),
        (
            "tides",
            "Find the sentence explaining why sailors learn the tide first.",
            "Sailors learn the tide before they learn much else, because it forgives nothing.",
            "clean",
            "13",
        ),
    ]
    for passage, instruction, phrase, difficulty, page in specs:
        CASE_SPECS.append(
            CaseSpec(
                id=f"{passage}-instruction-{difficulty}-{page}",
                passage=passage,
                instruction=instruction,
                modality="instruction",
                difficulty=difficulty,
                density="short",
                highlight=phrase,
                page_number=page,
            )
        )


def _register_dense() -> None:
    # The printing passage is the dense (~300 word) page.
    specs = [
        (
            "marker",
            "clean",
            "The arrival of movable type did not so much invent printing as make it patient and repeatable.",
            "Extract the highlighted sentence.",
            None,
            "141",
        ),
        (
            "marker",
            "degraded",
            "Cheaper books meant more readers; more readers meant a wider appetite for books",
            "Extract the highlighted text.",
            None,
            "142",
        ),
        (
            "underline",
            "clean",
            "A single volume might occupy a scribe for the better part of a year",
            "Extract the underlined text.",
            None,
            "140",
        ),
        (
            "marker",
            "clean",
            "Individual letters, cast in metal and arranged into lines, could be inked, pressed onto a sheet, and then broken apart and set again for the next page.",
            "Extract the highlighted multi-sentence passage.",
            "multi-sentence",
            "141",
        ),
    ]
    for modality, difficulty, phrase, instruction, edge, page in specs:
        CASE_SPECS.append(
            CaseSpec(
                id=f"printing-{modality}-{difficulty}-{page}-{edge or 'x'}",
                passage="printing",
                instruction=instruction,
                modality=modality,
                difficulty=difficulty,
                density="dense",
                highlight=phrase,
                edge_case=edge,
                page_number=page,
            )
        )


def _register_edge() -> None:
    # Multi-sentence highlight (short page).
    CASE_SPECS.append(
        CaseSpec(
            id="astronomy-multisentence-clean",
            passage="astronomy",
            instruction="Extract the highlighted passage.",
            modality="marker",
            difficulty="clean",
            density="short",
            highlight=(
                "Stars wheel overhead through the hours, and the whole pattern shifts a "
                "little westward each evening, so that the constellations of winter give "
                "way in time to the different company of summer."
            ),
            edge_case="multi-sentence",
            page_number="57",
        )
    )
    # Repeated-phrase disambiguation: highlight the FIRST occurrence; instruction
    # names the first paragraph so scoring (first-occurrence match) stays fair.
    CASE_SPECS.append(
        CaseSpec(
            id="sailing-repeated-clean",
            passage="sailing",
            instruction="Extract the first highlighted phrase (these two words recur later on the page).",
            modality="marker",
            difficulty="clean",
            density="short",
            highlight="by being",
            edge_case="repeated-phrase",
            page_number="22",
        )
    )
    CASE_SPECS.append(
        CaseSpec(
            id="beekeeping-repeated-degraded",
            passage="beekeeping",
            instruction="Extract the highlighted words from the first paragraph (the phrase appears twice).",
            modality="underline",
            difficulty="degraded",
            density="short",
            highlight="as one",
            edge_case="repeated-phrase",
            page_number="103",
        )
    )
    # Ambiguous instruction resolved by the visual highlight.
    CASE_SPECS.append(
        CaseSpec(
            id="bread-ambiguous-clean",
            passage="bread",
            instruction="Get the important part.",
            modality="marker",
            difficulty="clean",
            density="short",
            highlight="Flour, water, salt, and time will make a loaf",
            edge_case="ambiguous",
            page_number="76",
        )
    )
    CASE_SPECS.append(
        CaseSpec(
            id="sailing-ambiguous-warped",
            passage="sailing",
            instruction="Just the key bit.",
            modality="underline",
            difficulty="warped",
            density="short",
            highlight="Trimming is the quiet craft at the center of it all.",
            edge_case="ambiguous",
            page_number="24",
        )
    )
    # Hyphenated-line-break span: locate an actually-hyphenated word at render time.
    CASE_SPECS.extend(
        CaseSpec(
            id=f"cartography-hyphen-{difficulty}",
            passage="cartography",
            instruction="Extract the highlighted words (one is split across a line break).",
            modality="marker",
            difficulty=difficulty,
            density="short",
            edge_case="hyphenated",
            page_number="88",
            hyphen_target=True,
        )
        for difficulty in ("clean", "degraded")
    )
    CASE_SPECS.append(
        CaseSpec(
            id="printing-hyphen-clean",
            passage="printing",
            instruction="Extract the highlighted words (a word is hyphenated at the line break).",
            modality="underline",
            difficulty="clean",
            density="dense",
            edge_case="hyphenated",
            page_number="143",
            hyphen_target=True,
        )
    )


def _register_negative() -> None:
    specs = [
        ("gardening", "Extract the highlighted sentence.", "clean", "32"),
        ("astronomy", "Extract the highlighted text.", "degraded", "59"),
        ("tides", "Extract the underlined passage.", "clean", "11"),
        ("beekeeping", "Extract the highlighted phrase.", "warped", "105"),
        ("printing", "Extract the highlighted sentence.", "clean", "144"),
    ]
    for passage, instruction, difficulty, page in specs:
        density = "dense" if passage == "printing" else "short"
        CASE_SPECS.append(
            CaseSpec(
                id=f"{passage}-negative-{difficulty}",
                passage=passage,
                instruction=instruction,
                modality="none",
                difficulty=difficulty,
                density=density,
                highlight=None,
                is_negative=True,
                page_number=page,
            )
        )


def build_specs() -> list[CaseSpec]:
    CASE_SPECS.clear()
    _register_core()
    _register_instruction_only()
    _register_dense()
    _register_edge()
    _register_negative()
    return list(CASE_SPECS)


def _render_case(spec: CaseSpec, samples_dir: Path) -> dict:
    """Render one case image and return its dataset record."""
    passage = PASSAGES[spec.passage]
    font_size = 24 if spec.density == "dense" else 30
    rng = random.Random(_seed(spec.id))

    img, full_text, words = render_page(passage, font_size, spec.page_number)

    if spec.hyphen_target:
        found = _hyphen_span(words)
        if found is None:
            raise RuntimeError(f"{spec.id}: no hyphenated word found to highlight")
        start, end, _phrase, _word = found
        highlight = full_text[start:end]
    elif spec.is_negative or spec.highlight is None:
        start, end = 0, 0
        highlight = ""
    else:
        idx = full_text.find(spec.highlight)
        if idx == -1:
            raise RuntimeError(
                f"{spec.id}: highlight phrase not found in full_text: {spec.highlight!r}"
            )
        start, end = idx, idx + len(spec.highlight)
        highlight = spec.highlight

    if not spec.is_negative and spec.modality in ("marker", "underline"):
        boxes = _frag_boxes(words, start, end)
        if not boxes:
            raise RuntimeError(f"{spec.id}: no fragment boxes for span ({start},{end})")
        if spec.modality == "marker":
            composite_marker(img, boxes, rng)
        else:
            composite_underline(img, boxes, rng)
        if spec.add_bracket:
            composite_bracket(img, boxes, rng)

    final = degrade(img, spec.difficulty, rng)
    filename = f"{spec.id}.png"
    final.save(samples_dir / filename)

    return {
        "id": spec.id,
        "image_path": filename,
        "instruction": spec.instruction,
        "full_text": full_text,
        "expected_highlight": highlight,
        "expected_start": start,
        "expected_end": end,
        "expected_page_number": spec.page_number,
        "modality": spec.modality,
        "difficulty": spec.difficulty,
        "density": spec.density,
        "edge_case": spec.edge_case,
        "is_negative": spec.is_negative,
        "description": spec.instruction,
    }


def main() -> None:
    evals_dir = Path(__file__).parent
    samples_dir = evals_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)

    # Clear previously generated PNGs so removed cases don't linger.
    for old in samples_dir.glob("*.png"):
        old.unlink()

    specs = build_specs()
    cases = []
    hyphen_count = 0
    for spec in specs:
        record = _render_case(spec, samples_dir)
        cases.append(record)
        if spec.hyphen_target:
            hyphen_count += 1
        print(f"  rendered {spec.id}")

    dataset = {
        "version": "2.0",
        "description": (
            "Synthetic-realistic highlight-extraction dataset. Original neutral prose "
            "rendered as book pages with composited visual highlights and photo-realism "
            "degradations. Ground truth known by construction."
        ),
        "cases": cases,
    }
    dataset_path = samples_dir / "dataset.json"
    with open(dataset_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)

    print(f"\nGenerated {len(cases)} cases -> {dataset_path}")
    print(f"Hyphenation edge cases: {hyphen_count}")


if __name__ == "__main__":
    main()
