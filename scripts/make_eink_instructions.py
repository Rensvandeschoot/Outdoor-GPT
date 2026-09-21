"""Build the start-up instruction card for the e-ink screen from the photo
of the OutdoorGPT concept render (eink_instructions_source.jpg).

The four instruction panels are located in the photo, each is warped flat,
the uneven lighting is divided out so the card ground comes out white and
the ink black, and the result is snapped to the four grey levels the
Waveshare 7.5" V2 can show. The panels in the photo are about the size of
the cards on the screen, so the artwork is reproduced at its own resolution:
the bark strokes, the growth rings, the ribbing on the box all survive.

Writes eink_instructions.png next to this file, in the screen's render
orientation (480x800 portrait, 2x2; or 800x480 landscape, one row) from
device_settings.py. The display code fits the image to the screen either
way, and any picture Pillow can open may replace it under the same name.

Run on the PC (needs Pillow, numpy, scipy):
    python scripts/make_eink_instructions.py [photo]
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import device_settings  # noqa: E402

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "eink_instructions_source.jpg")
OUT = os.path.join(HERE, device_settings.EINK_INSTRUCTIONS_IMAGE)

EPD_WIDTH, EPD_HEIGHT = 800, 480
PORTRAIT = device_settings.EINK_ORIENTATION == "portrait"
W, H = (EPD_HEIGHT, EPD_WIDTH) if PORTRAIT else (EPD_WIDTH, EPD_HEIGHT)
MARGIN, GUTTER = 10, 10

# The panel's four grey levels, exactly as the driver's 4-grey mode expects.
WHITE, LIGHT, DARK, BLACK = 0xFF, 0xC0, 0x80, 0x00
# Cut points between them. Slightly below the midpoints, so anti-aliased
# edges lean towards the ink and solid fills stay solid.
CUTS = (70, 150, 215)


# ------------------------------------------------------------ find the cards

def find_cards(gray):
    """Corner quads (TL, TR, BR, BL) of the four white cards, left to right."""
    a = np.asarray(gray, dtype=np.uint8)
    bright = a > 150
    lab, n = ndimage.label(bright)
    sizes = ndimage.sum(bright, lab, range(1, n + 1))
    slices = ndimage.find_objects(lab)
    cands = []
    for i, s in enumerate(sizes, start=1):
        if not 20000 <= s <= 200000:
            continue
        ys, xs = slices[i - 1]
        w, h = xs.stop - xs.start, ys.stop - ys.start
        if 0.35 < w / h < 0.9:
            cands.append((i, xs.start, xs.stop, ys.start, ys.stop))
    cands.sort(key=lambda c: c[1])
    if len(cands) < 4:
        sys.exit(f"found {len(cands)} card-sized white areas, expected 4")
    cands = cands[:4]
    top = min(c[3] for c in cands)
    bot = max(c[4] for c in cands)

    quads = []
    for _, x0, x1, _, _ in cands:
        # All bright pieces in this card's column: a pictogram's ground line
        # can cut the white card in two.
        mask = np.zeros_like(bright)
        for j, sl in enumerate(slices, start=1):
            if sl is None:
                continue
            ys, xs = sl
            if xs.start >= x0 - 4 and xs.stop <= x1 + 5 and ys.start >= top - 4 and ys.stop <= bot + 5:
                mask |= lab == j
        mask = ndimage.binary_fill_holes(mask)
        ys, xs = np.nonzero(mask)
        s, d = xs + ys, xs - ys
        quads.append([(xs[s.argmin()], ys[s.argmin()]), (xs[d.argmax()], ys[d.argmax()]),
                      (xs[s.argmax()], ys[s.argmax()]), (xs[d.argmin()], ys[d.argmin()])])

    # The cards share one bottom edge. A card whose detected bottom sits well
    # above the others (a shadow, or a ground line reaching the outline) gets
    # its bottom corners from the line through the other cards' corners.
    hts = [q[3][1] - q[0][1] for q in quads]
    full = [q for q, h in zip(quads, hts) if h >= 0.97 * max(hts)]
    pts = [q[2] for q in full] + [q[3] for q in full]
    m, c = np.polyfit([float(x) for x, _ in pts], [float(y) for _, y in pts], 1)
    for q, h in zip(quads, hts):
        if h < 0.97 * max(hts):
            blx, brx = q[0][0] - 3, q[1][0] + 4
            q[2] = (brx, int(round(m * brx + c)))
            q[3] = (blx, int(round(m * blx + c)))
    return [[(int(x), int(y)) for x, y in q] for q in quads]


def perspective_coeffs(src_pts, dst_pts):
    """Pillow's 8 coefficients mapping output (dst) points to input (src)."""
    A, b = [], []
    for (x, y), (u, v) in zip(dst_pts, src_pts):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b += [u, v]
    return np.linalg.solve(np.array(A, dtype=np.float64), np.array(b, dtype=np.float64))


# ------------------------------------------------------------ clean one card

def flatten_and_stretch(card):
    """Divide out the lighting (fitted on the light ground only, so the big
    dark shapes do not pull it), then put the ground at white and the darkest
    ink at black."""
    a = np.asarray(card, dtype=np.float64)
    h, w = a.shape
    yy, xx = np.mgrid[0:h, 0:w]
    x, y, v = xx.ravel() / w, yy.ravel() / h, a.ravel()
    X = np.stack([np.ones_like(x), x, y, x * x, x * y, y * y], axis=1)
    ground = v > np.percentile(v, 55)
    coef, *_ = np.linalg.lstsq(X[ground], v[ground], rcond=None)
    illum = (X @ coef).reshape(h, w)
    flat = a / np.maximum(illum, 1.0) * 255.0
    ink = flat[flat < 128]
    black = np.percentile(ink, 3) if ink.size else 0.0
    out = (flat - black) / max(255.0 - black, 1.0) * 255.0
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def snap(img):
    lut = [BLACK if v < CUTS[0] else DARK if v < CUTS[1] else LIGHT if v < CUTS[2] else WHITE
           for v in range(256)]
    return img.point(lut)


# ---------------------------------------------------------------------- main

def main():
    photo = Image.open(SRC).convert("L")
    quads = find_cards(photo)

    cols, rows = (2, 2) if PORTRAIT else (4, 1)
    cell_w = (W - 2 * MARGIN - (cols - 1) * GUTTER) // cols
    cell_h = (H - 2 * MARGIN - (rows - 1) * GUTTER) // rows
    # Card size: the source aspect, fitted in the cell.
    src_aspect = np.mean([(q[1][0] - q[0][0]) / (q[3][1] - q[0][1]) for q in quads])
    cw = min(cell_w, int(cell_h * src_aspect))
    ch = int(cw / src_aspect)
    radius = int(cw * 0.06)

    out = Image.new("L", (W, H), WHITE)
    draw = ImageDraw.Draw(out)
    for k, quad in enumerate(quads):
        tw, th = cw * 2, ch * 2                       # warp at 2x, shrink once
        coeffs = perspective_coeffs(quad, [(0, 0), (tw, 0), (tw, th), (0, th)])
        card = photo.transform((tw, th), Image.PERSPECTIVE, coeffs, Image.BICUBIC)
        card = flatten_and_stretch(card)
        card = card.filter(ImageFilter.UnsharpMask(radius=2, percent=90, threshold=2))
        card = card.resize((cw, ch), Image.LANCZOS)
        # Rounded corners: the warp's corner pixels come from the outline.
        mask = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw - 1, ch - 1), radius=radius, fill=255)
        card = Image.composite(card, Image.new("L", (cw, ch), WHITE), mask)

        c, r = k % cols, k // cols
        x0 = MARGIN + c * (cell_w + GUTTER) + (cell_w - cw) // 2
        y0 = MARGIN + r * (cell_h + GUTTER) + (cell_h - ch) // 2
        out.paste(card, (x0, y0))
        draw.rounded_rectangle((x0, y0, x0 + cw - 1, y0 + ch - 1), radius=radius,
                               outline=DARK, width=3)

    snap(out).save(OUT)
    print(f"wrote {OUT}  ({W}x{H}, {'portrait 2x2' if PORTRAIT else 'landscape 1x4'}, "
          f"cards {cw}x{ch}, 4 grey levels)")


if __name__ == "__main__":
    main()
