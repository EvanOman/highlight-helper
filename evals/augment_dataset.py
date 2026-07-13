#!/usr/bin/env python3
"""Additive phone-photo augmentation pass for the synthetic eval dataset.

The W1 generator (:mod:`evals.generate_dataset`) renders full-frame book pages
with composited highlights and light photo-realism degradation. Those 48 cases
are *clean-render flattery*: the page fills the frame, sits square, and is evenly
lit. Real phone photos are messier — the page sits on a desk with context around
it, tilted, keystoned by the camera angle, and lit unevenly with a colour cast.

This module takes the *already-rendered* parent page images and their known
ground truth and produces harder variants **without touching the text**:

1. Background compositing (wood desk / fabric / dark table / cluttered gradient),
   page occupying 70-95% of the frame, offset and rotated.
2. Rotation up to +/-15 deg with background fill.
3. Perspective / keystone stronger than the generator's quad warp.
4. Photometric: colour-temperature shift, uneven exposure, vignette, sensor
   noise, slight motion blur, and (on hard) a soft glare.

Graded easy / medium / hard. Everything is seeded from the augmented case id, so
regeneration is byte-deterministic. Ground truth (``full_text``, highlight text,
char span, page number, and every parent category label) is inherited verbatim:
the geometry and photometrics never move a glyph relative to the page, and the
page is never occluded (backgrounds sit *behind* it; photometrics are global and
translucent), so the parent's labels remain correct by construction.

Augmented cases are ADDITIVE (see decision D4): the 48 originals and their PNGs
are never regenerated. New cases get ids ``{parent_id}-aug-{level}`` plus a
``parent_id`` field and an ``augmentation:{level}`` category tag, while keeping
all the parent's other labels so rollups slice both ways.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from zlib import crc32

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# Reuse the W1 photo-realism machinery rather than pull in opencv/Albumentations.
# (Noise is regenerated with a seeded numpy RNG instead of PIL's Image.effect_noise,
# which draws from an internal RNG that Python's `random.seed` can't control — so
# reusing it would break byte-for-byte determinism.)
from evals.generate_dataset import _add_glare, _small_gradient

# --- Frame geometry --------------------------------------------------------
# Parent pages render at 1000x1400. The frame is a bit larger and phone-ish so
# the page can occupy 70-95% of it with real background context around the edge.
FRAME_W = 1280
FRAME_H = 1600
FRAME = (FRAME_W, FRAME_H)
# The page's four corners are always kept at least this many px inside the frame,
# so no part of the page (hence no text) is ever clipped by the frame edge.
FRAME_MARGIN = 24

BACKGROUNDS = ("wood", "fabric", "dark", "cluttered")


def _gray_noise(size: tuple[int, int], sigma: float, seed: int) -> Image.Image:
    """A deterministic single-channel Gaussian-noise image (mean 128).

    Seeded via numpy so ``seed`` fully determines the pixels — unlike PIL's
    ``Image.effect_noise``, which is not controllable from ``random.seed``.
    """
    w, h = size
    gen = np.random.default_rng(seed)
    arr = np.clip(gen.normal(128.0, sigma, (h, w)), 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "L")


def _add_noise(img: Image.Image, rng: random.Random, sigma: float) -> Image.Image:
    """Blend seeded grayscale sensor noise over ``img`` (11% opacity, like W1)."""
    noise = _gray_noise(img.size, sigma, rng.randint(0, 2**31 - 1))
    noise_rgb = Image.merge("RGB", (noise, noise, noise))
    return Image.blend(img.convert("RGB"), noise_rgb, alpha=0.11)


@dataclass(frozen=True)
class Level:
    """Augmentation parameter envelope for one difficulty grade."""

    occupancy: tuple[float, float]  # page's fitted fraction of the frame
    rotation_deg: float  # max abs rotation
    keystone: tuple[float, float]  # perspective edge-compression fraction
    jitter: float  # translation jitter as a fraction of frame size
    temp: float  # colour-temperature strength
    exposure: tuple[float, float]  # (min, max) multiplier across the gradient
    vignette: float  # darkest multiplier at the frame corners (1.0 = none)
    noise: tuple[float, float]  # sensor-noise sigma range
    motion: int  # motion-blur kernel length in px (0 = none)
    blur: float  # gaussian blur radius
    glare: bool  # add a soft specular glare


LEVELS: dict[str, Level] = {
    "easy": Level(
        occupancy=(0.85, 0.95),
        rotation_deg=5.0,
        keystone=(0.00, 0.04),
        jitter=0.03,
        temp=0.03,
        exposure=(0.92, 1.06),
        vignette=0.90,
        noise=(3.0, 6.0),
        motion=0,
        blur=0.0,
        glare=False,
    ),
    "medium": Level(
        occupancy=(0.78, 0.90),
        rotation_deg=10.0,
        keystone=(0.03, 0.09),
        jitter=0.05,
        temp=0.06,
        exposure=(0.82, 1.14),
        vignette=0.80,
        noise=(6.0, 10.0),
        motion=4,
        blur=0.5,
        glare=False,
    ),
    "hard": Level(
        occupancy=(0.70, 0.85),
        rotation_deg=15.0,
        keystone=(0.07, 0.15),
        jitter=0.07,
        temp=0.10,
        exposure=(0.72, 1.20),
        vignette=0.64,
        noise=(10.0, 16.0),
        motion=8,
        blur=1.0,
        glare=True,
    ),
}

# Representative parents: cover marker / underline / instruction / negative,
# clean + dense, plus the hyphenated / repeated-phrase / multi-sentence edges.
# All are clean-difficulty bases so the augmentation is the only degradation
# stacked on top (an honest measurement of augmentation-only effect).
PARENT_IDS: list[str] = [
    "sailing-marker-clean",  # marker / short
    "tides-marker-clean",  # marker / short
    "beekeeping-underline-clean",  # underline / short
    "gardening-instruction-clean-31",  # instruction-only
    "gardening-negative-clean",  # negative (modality:none)
    "printing-marker-clean-141-x",  # marker / dense
    "printing-underline-clean-140-x",  # underline / dense
    "cartography-hyphen-clean",  # edge:hyphenated
    "sailing-repeated-clean",  # edge:repeated-phrase
    "astronomy-multisentence-clean",  # edge:multi-sentence
]


def _seed(case_id: str) -> int:
    return crc32(case_id.encode()) & 0xFFFFFFFF


Corner = tuple[float, float]
Quad = tuple[Corner, Corner, Corner, Corner]


# --- Placement geometry ----------------------------------------------------
def _rotate_pt(x: float, y: float, cos: float, sin: float) -> Corner:
    return (x * cos - y * sin, x * sin + y * cos)


def page_placement(
    frame: tuple[int, int],
    page: tuple[int, int],
    level: Level,
    rng: random.Random,
) -> Quad:
    """Return the page's four destination corners inside the frame.

    Order is (TL, TR, BR, BL), matching the page source corners
    ``(0,0), (pw,0), (pw,ph), (0,ph)``. The page is scaled to a fraction of the
    frame, rotated, keystoned, and jittered — then a deterministic shrink-to-fit
    step guarantees all four corners land within ``FRAME_MARGIN`` of every edge,
    so the whole page (and its text) is always fully inside the frame.
    """
    fw, fh = frame
    pw, ph = page

    occ = rng.uniform(*level.occupancy)
    fit = occ * min(fw / pw, fh / ph)
    hw, hh = pw * fit / 2.0, ph * fit / 2.0

    # Local corners about the page centre, before perspective/rotation.
    local = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]

    # Keystone: compress one edge toward the centre to fake a camera tilt.
    k = rng.uniform(*level.keystone)
    edge = rng.choice(("top", "bottom", "left", "right"))
    if edge == "top":
        local[0] = (local[0][0] + k * hw, local[0][1])
        local[1] = (local[1][0] - k * hw, local[1][1])
    elif edge == "bottom":
        local[3] = (local[3][0] + k * hw, local[3][1])
        local[2] = (local[2][0] - k * hw, local[2][1])
    elif edge == "left":
        local[0] = (local[0][0], local[0][1] + k * hh)
        local[3] = (local[3][0], local[3][1] - k * hh)
    else:  # right
        local[1] = (local[1][0], local[1][1] + k * hh)
        local[2] = (local[2][0], local[2][1] - k * hh)

    # Rotation about the centre.
    theta = math.radians(rng.uniform(-level.rotation_deg, level.rotation_deg))
    cos, sin = math.cos(theta), math.sin(theta)
    rotated = [_rotate_pt(x, y, cos, sin) for x, y in local]

    # Translation: frame centre plus a jitter.
    cx = fw / 2.0 + rng.uniform(-level.jitter, level.jitter) * fw
    cy = fh / 2.0 + rng.uniform(-level.jitter, level.jitter) * fh
    corners = [(x + cx, y + cy) for x, y in rotated]

    corners = _fit_inside(corners, fw, fh, FRAME_MARGIN)
    tl, tr, br, bl = corners
    return (tl, tr, br, bl)


def _fit_inside(corners: list[Corner], fw: int, fh: int, margin: int) -> list[Corner]:
    """Scale toward the centroid (if needed) then translate so every corner sits
    within ``[margin, dim - margin]`` on both axes. Deterministic, no randomness."""
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    bw, bh = max(xs) - min(xs), max(ys) - min(ys)
    avail_w, avail_h = fw - 2 * margin, fh - 2 * margin

    scale = min(1.0, avail_w / bw if bw > 0 else 1.0, avail_h / bh if bh > 0 else 1.0)
    if scale < 1.0:
        gx = sum(xs) / len(xs)
        gy = sum(ys) / len(ys)
        corners = [(gx + (x - gx) * scale, gy + (y - gy) * scale) for x, y in corners]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]

    dx = 0.0
    if min(xs) < margin:
        dx = margin - min(xs)
    elif max(xs) > fw - margin:
        dx = (fw - margin) - max(xs)
    dy = 0.0
    if min(ys) < margin:
        dy = margin - min(ys)
    elif max(ys) > fh - margin:
        dy = (fh - margin) - max(ys)
    return [(x + dx, y + dy) for x, y in corners]


def _perspective_coeffs(dst: Quad, src: Quad) -> list[float]:
    """8 PIL PERSPECTIVE coefficients mapping output ``dst`` corners back to input
    ``src`` corners (PIL samples input at ``coeffs`` applied to each output pixel)."""
    a = []
    b = []
    for (xd, yd), (xs, ys) in zip(dst, src, strict=True):
        a.append([xd, yd, 1, 0, 0, 0, -xs * xd, -xs * yd])
        a.append([0, 0, 0, xd, yd, 1, -ys * xd, -ys * yd])
        b.append(xs)
        b.append(ys)
    coeffs = np.linalg.solve(np.array(a, dtype=float), np.array(b, dtype=float))
    return coeffs.tolist()


# --- Procedural backgrounds ------------------------------------------------
def _linear_ramp(size: tuple[int, int], angle: float) -> np.ndarray:
    """A 0..1 linear gradient across ``angle`` radians, shape (h, w)."""
    w, h = size
    xs = np.linspace(-1.0, 1.0, w)
    ys = np.linspace(-1.0, 1.0, h)
    gx, gy = np.meshgrid(xs, ys)
    proj = gx * math.cos(angle) + gy * math.sin(angle)
    span = float(np.ptp(proj))
    return (proj - proj.min()) / (span or 1.0)


def _make_background(kind: str, size: tuple[int, int], rng: random.Random) -> Image.Image:
    """A procedurally generated RGB background frame."""
    w, h = size
    seed = rng.randint(0, 2**31 - 1)
    if kind == "wood":
        base = np.array([rng.randint(120, 165), rng.randint(80, 110), rng.randint(45, 70)])
        ramp = _linear_ramp(size, rng.uniform(0, math.pi))[:, :, None]
        img = base[None, None, :] * (0.82 + 0.28 * ramp)
        # Vertical plank grain: stacked sinusoids along x.
        xs = np.arange(w)
        grain = np.zeros(w)
        for freq, amp in ((0.05, 10), (0.017, 16), (0.006, 22)):
            grain += amp * np.sin(freq * xs + rng.uniform(0, 6.28))
        img += grain[None, :, None]
    elif kind == "fabric":
        base = np.array([rng.randint(70, 150), rng.randint(70, 150), rng.randint(80, 160)])
        img = np.tile(base[None, None, :].astype(float), (h, w, 1))
        weave = np.arange(w)[None, :] % 8 + np.arange(h)[:, None] % 8
        img += (weave[:, :, None] - 7) * 2.2
    elif kind == "dark":
        base = np.array([rng.randint(28, 52), rng.randint(26, 48), rng.randint(24, 44)])
        ramp = _linear_ramp(size, rng.uniform(0, math.pi))[:, :, None]
        img = base[None, None, :] * (0.7 + 0.6 * ramp)
    else:  # cluttered gradient
        c0 = np.array([rng.randint(60, 200) for _ in range(3)])
        c1 = np.array([rng.randint(40, 180) for _ in range(3)])
        ramp = _linear_ramp(size, rng.uniform(0, 2 * math.pi))[:, :, None]
        img = c0[None, None, :] * (1 - ramp) + c1[None, None, :] * ramp

    rgb = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")

    if kind == "cluttered":
        # A few soft out-of-focus "objects" around (never over) the page.
        draw = ImageDraw.Draw(rgb, "RGBA")
        blob_rng = random.Random(seed)
        for _ in range(blob_rng.randint(3, 6)):
            bx, by = blob_rng.uniform(0, w), blob_rng.uniform(0, h)
            r = blob_rng.uniform(60, 180)
            col = (*(blob_rng.randint(30, 220) for _ in range(3)), blob_rng.randint(40, 110))
            draw.ellipse([bx - r, by - r, bx + r, by + r], fill=col)
        rgb = rgb.filter(ImageFilter.GaussianBlur(rng.uniform(6, 14)))

    # A little grain so backgrounds never look plasticky.
    texture_sigma = {"wood": 6.0, "fabric": 10.0, "dark": 5.0, "cluttered": 4.0}[kind]
    noise = _gray_noise(size, texture_sigma, seed ^ 0x5EED)
    rgb = Image.blend(rgb, Image.merge("RGB", (noise, noise, noise)), alpha=0.06)
    if kind in ("wood", "fabric"):
        rgb = rgb.filter(ImageFilter.GaussianBlur(0.6))
    return rgb


# --- Photometric passes ----------------------------------------------------
def _color_temperature(img: Image.Image, rng: random.Random, amt: float) -> Image.Image:
    """Warm (boost R, cut B) or cool (the reverse) colour cast."""
    if amt <= 0:
        return img
    warm = rng.random() < 0.5
    a = amt if warm else -amt
    r, g, b = img.split()
    r = r.point(lambda v: min(255, int(v * (1 + a))))
    b = b.point(lambda v: min(255, int(v * (1 - a))))
    return Image.merge("RGB", (r, g, b))


def _uneven_exposure(img: Image.Image, rng: random.Random, lo: float, hi: float) -> Image.Image:
    """Multiply by a low-frequency linear brightness gradient (one side brighter)."""
    ramp = _linear_ramp(img.size, rng.uniform(0, 2 * math.pi))
    mask = lo + (hi - lo) * ramp
    arr = np.asarray(img, dtype=float) * mask[:, :, None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def _vignette(img: Image.Image, rng: random.Random, dark: float) -> Image.Image:
    """Radial corner darkening (reuses the W1 gradient mask)."""
    if dark >= 1.0:
        return img
    mask = _small_gradient(img.size, rng, dark)
    arr = np.asarray(img, dtype=float) * (np.asarray(mask, dtype=float) / 255.0)[:, :, None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def _motion_blur(img: Image.Image, rng: random.Random, length: int) -> Image.Image:
    """Directional blur by averaging a few translated copies along a random axis."""
    if length < 2:
        return img
    angle = rng.uniform(0, math.pi)
    dx, dy = math.cos(angle), math.sin(angle)
    arr = np.asarray(img, dtype=float)
    acc = np.zeros_like(arr)
    for i in range(length):
        off = i - (length - 1) / 2.0
        acc += np.roll(arr, (round(off * dy), round(off * dx)), axis=(0, 1))
    acc /= length
    return Image.fromarray(np.clip(acc, 0, 255).astype(np.uint8), "RGB")


# --- Full augmentation -----------------------------------------------------
def augment_image(
    page: Image.Image, level_name: str, seed: int, background: str | None = None
) -> Image.Image:
    """Composite ``page`` onto a background and apply the graded degradation stack.

    Deterministic in ``seed``: same seed (and inputs) -> same output pixels.
    """
    level = LEVELS[level_name]
    rng = random.Random(seed)

    page = page.convert("RGBA")
    kind = background or rng.choice(BACKGROUNDS)
    bg = _make_background(kind, FRAME, rng).convert("RGBA")

    src: Quad = ((0, 0), (page.width, 0), (page.width, page.height), (0, page.height))
    dst = page_placement(FRAME, page.size, level, rng)
    coeffs = _perspective_coeffs(dst, src)
    warped = page.transform(
        FRAME, Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC, fillcolor=(0, 0, 0, 0)
    )
    frame = Image.alpha_composite(bg, warped).convert("RGB")

    # Photometrics, applied globally over the whole frame (never occluding text).
    frame = _color_temperature(frame, rng, level.temp)
    frame = _uneven_exposure(frame, rng, *level.exposure)
    frame = _vignette(frame, rng, level.vignette)
    if level.glare:
        frame = _add_glare(frame, rng)
    if level.blur > 0:
        frame = frame.filter(ImageFilter.GaussianBlur(rng.uniform(0.4, level.blur)))
    frame = _motion_blur(frame, rng, level.motion)
    return _add_noise(frame, rng, rng.uniform(*level.noise))


def _augment_record(parent: dict, level_name: str, samples_dir: Path) -> dict:
    """Render one augmented image and return its dataset record (ground truth
    inherited verbatim from ``parent``)."""
    aug_id = f"{parent['id']}-aug-{level_name}"
    page = Image.open(samples_dir / parent["image_path"])
    out = augment_image(page, level_name, _seed(aug_id))
    filename = f"{aug_id}.png"
    out.save(samples_dir / filename)

    record = dict(parent)  # inherit full_text, span, page number, all labels
    record["id"] = aug_id
    record["image_path"] = filename
    record["parent_id"] = parent["id"]
    record["augmentation"] = level_name
    record["description"] = (
        f"{parent.get('description') or parent['instruction']} "
        f"[augmented: {level_name} phone-photo variant of {parent['id']}]"
    )
    return record


def build_augmented(dataset_path: Path) -> list[dict]:
    """Regenerate every augmented case, rewriting ``dataset.json`` additively.

    The 48 original case dicts are preserved byte-for-byte (they are not routed
    through any dataclass), any prior ``*-aug-*`` entries/images are replaced, and
    the new augmented records are appended.
    """
    samples_dir = dataset_path.parent
    with open(dataset_path, encoding="utf-8") as f:
        data = json.load(f)

    originals = [c for c in data["cases"] if "-aug-" not in c["id"]]
    by_id = {c["id"]: c for c in originals}

    # Clear stale augmented images so a removed variant never lingers.
    for old in samples_dir.glob("*-aug-*.png"):
        old.unlink()

    augmented: list[dict] = []
    for parent_id in PARENT_IDS:
        parent = by_id.get(parent_id)
        if parent is None:
            raise RuntimeError(f"parent case not found in dataset: {parent_id!r}")
        for level_name in ("easy", "medium", "hard"):
            record = _augment_record(parent, level_name, samples_dir)
            augmented.append(record)
            print(f"  rendered {record['id']}")

    data["cases"] = originals + augmented
    with open(dataset_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return augmented


def main() -> None:
    dataset_path = Path(__file__).parent / "samples" / "dataset.json"
    augmented = build_augmented(dataset_path)
    by_level: dict[str, int] = {}
    for rec in augmented:
        by_level[rec["augmentation"]] = by_level.get(rec["augmentation"], 0) + 1
    print(f"\nGenerated {len(augmented)} augmented cases -> {dataset_path}")
    print(f"By level: {by_level}")


if __name__ == "__main__":
    main()
