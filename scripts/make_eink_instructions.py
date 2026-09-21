"""Draw the start-up instruction card for the e-ink screen.

Four numbered pictograms, after the card on the OutdoorGPT concept render:
1 cut down a tree, 2 put the box on the stump, 3 turn the crank, 4 talk to
the AI. Drawn in the four grey levels the Waveshare 7.5" V2 can show
(white, light grey, dark grey, black), which is what gives the card the look
of the original: white cards on a grey ground, the box and the stump shaded.
Writes eink_instructions.png next to this file, in the screen's render
orientation (480x800 portrait or 800x480 landscape, from device_settings.py).
The display code fits the image to the screen either way, and any picture
Pillow can open may replace it under the same name.

Run on the PC (needs Pillow):   python scripts/make_eink_instructions.py
"""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import device_settings  # noqa: E402

EPD_WIDTH, EPD_HEIGHT = 800, 480
PORTRAIT = device_settings.EINK_ORIENTATION == "portrait"
W, H = (EPD_HEIGHT, EPD_WIDTH) if PORTRAIT else (EPD_WIDTH, EPD_HEIGHT)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   device_settings.EINK_INSTRUCTIONS_IMAGE)

SS = 4                  # supersample: draw large, shrink, snap to the four levels

# The panel's four grey levels, as the driver defines them (epd7in5_V2.py).
WHITE, LIGHT, DARK, BLACK = 0xFF, 0xC0, 0x80, 0x00
LEVELS = (BLACK, DARK, LIGHT, WHITE)

_FONTS_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]


def font(size):
    for p in _FONTS_BOLD:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    try:
        return ImageFont.load_default(size)
    except TypeError:               # Pillow < 10.1 has no sized default
        return ImageFont.load_default()


class Panel:
    """One numbered card.

    Pictograms are drawn in unit coordinates (u to the right, v down) over a
    box of fixed aspect ratio below the number badge, so the same drawing
    code gives undistorted shapes in both screen orientations. `s` is the
    box width, used for radii and stroke widths.
    """
    ASPECT = 0.58   # box width / height

    def __init__(self, draw, box, number):
        self.d = draw
        x0, y0, x1, y1 = box
        pw = x1 - x0
        draw.rounded_rectangle(box, radius=int(pw * 0.07), fill=WHITE, outline=DARK,
                               width=max(2, int(pw * 0.018)))
        br = int(pw * 0.085)
        bx, by = x0 + int(pw * 0.14), y0 + int(pw * 0.14)
        draw.ellipse((bx - br, by - br, bx + br, by + br), fill=BLACK)
        draw.text((bx, by), str(number), fill=WHITE, font=font(int(br * 1.45)), anchor="mm")
        pad = int(pw * 0.09)
        ax, ay = x0 + pad, by + br + pad // 2
        aw, ah = pw - 2 * pad, (y1 - pad) - ay
        bw = min(aw, ah * self.ASPECT)
        bh = bw / self.ASPECT
        self.ax = ax + (aw - bw) / 2
        self.ay = ay + (ah - bh) / 2
        self.s = bw
        self.bh = bh

    def p(self, u, v):
        return (self.ax + u * self.s, self.ay + v * self.bh)

    def pts(self, *uv):
        return [self.p(u, v) for u, v in uv]

    def stroke(self, k=0.03):
        return max(2, int(self.s * k))

    def circle(self, u, v, r, fill, outline=None, k=0.02):
        x, y = self.p(u, v)
        R = r * self.s
        self.d.ellipse((x - R, y - R, x + R, y + R), fill=fill, outline=outline,
                       width=self.stroke(k) if outline is not None else 0)

    def line(self, a, b, k=0.03, fill=BLACK):
        self.d.line([self.p(*a), self.p(*b)], fill=fill, width=self.stroke(k))


# ----------------------------------------------------------------- shared parts

def stump(P, cx, top_v, bot_v, hw):
    """A cut tree stump: dark grey wood with black bark lines and outline,
    a light top face with black growth rings, flared roots."""
    d = P.d
    ry = 0.045
    body = P.pts((cx - hw, top_v), (cx + hw, top_v),
                 (cx + hw * 1.05, bot_v - 0.03), (cx + hw * 1.4, bot_v),
                 (cx - hw * 1.4, bot_v), (cx - hw * 1.05, bot_v - 0.03))
    d.polygon(body, fill=DARK, outline=BLACK, width=P.stroke(0.02))
    for u in (cx - hw * 0.45, cx, cx + hw * 0.45):        # bark grooves
        P.line((u, top_v + ry + 0.03), (u, bot_v - 0.06), k=0.018, fill=BLACK)
    x0, y0 = P.p(cx - hw, top_v - ry)
    x1, y1 = P.p(cx + hw, top_v + ry)
    d.ellipse((x0, y0, x1, y1), fill=LIGHT, outline=BLACK, width=P.stroke(0.025))
    for k in (0.66, 0.36):                                 # growth rings
        ex0, ey0 = P.p(cx - hw * k, top_v - ry * k)
        ex1, ey1 = P.p(cx + hw * k, top_v + ry * k)
        d.ellipse((ex0, ey0, ex1, ey1), outline=BLACK, width=P.stroke(0.018))


def device(P, u0, v0, u1, v1):
    """The crank box: a dark grey ribbed case with a black outline, a lighter
    lid strip and a white screen."""
    d = P.d
    x0, y0 = P.p(u0, v0)
    x1, y1 = P.p(u1, v1)
    r = int((x1 - x0) * 0.10)
    d.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=DARK, outline=BLACK,
                        width=P.stroke(0.022))
    lid_h = (y1 - y0) * 0.42                               # lighter lid
    d.rounded_rectangle((x0, y0, x1, y0 + lid_h), radius=r, fill=LIGHT, outline=BLACK,
                        width=P.stroke(0.022))
    d.rectangle((x0, y0 + lid_h * 0.5, x1, y0 + lid_h), fill=LIGHT)
    d.line([(x0, y0 + lid_h), (x1, y0 + lid_h)], fill=BLACK, width=P.stroke(0.022))
    n = 5
    for i in range(1, n):                                  # ribs on the case
        y = y0 + lid_h + (y1 - y0 - lid_h) * i / n
        d.line([(x0 + r * 0.7, y), (x1 - r * 0.7, y)], fill=BLACK, width=max(1, P.stroke(0.012)))
    sw, sh = (x1 - x0) * 0.46, lid_h * 0.62                # screen in the lid
    sx, sy = x0 + (x1 - x0) * 0.09, y0 + lid_h * 0.19
    d.rectangle((sx, sy, sx + sw, sy + sh), fill=WHITE, outline=BLACK, width=P.stroke(0.015))


def arrowhead(P, u, v, du, dv, size):
    """Filled triangle with its tip at (u, v), pointing along (du, dv)."""
    n = (du * du + dv * dv) ** 0.5
    du, dv = du / n, dv / n
    px, py = -dv, du                                       # perpendicular
    tip = (u, v)
    base = (u - du * size, v - dv * size)
    left = (base[0] + px * size * 0.6, base[1] + py * size * 0.6)
    right = (base[0] - px * size * 0.6, base[1] - py * size * 0.6)
    P.d.polygon(P.pts(tip, left, right), fill=BLACK)


# ---------------------------------------------------------------- the panels

def draw_chop(P):
    """1: a person swings an axe into the base of a pine."""
    d = P.d
    P.line((0.02, 0.90), (0.98, 0.90), k=0.02)             # ground
    for u in (0.06, 0.12, 0.88, 0.94):                     # grass
        P.line((u, 0.90), (u + 0.02, 0.85), k=0.015)
    cx = 0.75                                              # pine, shaded on the right
    for tip, base, hw in ((0.03, 0.33, 0.16), (0.17, 0.51, 0.21), (0.33, 0.69, 0.25)):
        d.polygon(P.pts((cx, tip), (cx - hw, base), (cx + hw, base)), fill=BLACK)
        d.polygon(P.pts((cx, tip + 0.02), (cx, base), (cx + hw - 0.02, base)), fill=DARK)
    d.rectangle([P.p(cx - 0.045, 0.67), P.p(cx + 0.045, 0.90)], fill=BLACK)
    for u, v in ((0.60, 0.56), (0.67, 0.60), (0.63, 0.50)):   # chips flying off the trunk
        d.polygon(P.pts((u, v), (u + 0.035, v + 0.01), (u + 0.01, v + 0.03)), fill=BLACK)
    # the woodcutter: a filled silhouette leaning into the swing
    P.circle(0.25, 0.29, 0.065, BLACK)                     # head
    d.polygon(P.pts((0.19, 0.33), (0.32, 0.33), (0.36, 0.47), (0.33, 0.61),
                    (0.20, 0.61), (0.17, 0.48)), fill=BLACK)   # torso
    P.line((0.23, 0.60), (0.12, 0.90), k=0.07)              # back leg
    P.line((0.31, 0.60), (0.38, 0.90), k=0.07)              # front leg
    P.line((0.31, 0.40), (0.52, 0.56), k=0.06)              # arms to the grip
    P.line((0.26, 0.45), (0.50, 0.58), k=0.055)
    P.line((0.49, 0.55), (0.64, 0.73), k=0.035)             # axe handle
    d.polygon(P.pts((0.57, 0.66), (0.66, 0.70), (0.72, 0.77), (0.71, 0.88),
                    (0.62, 0.84), (0.55, 0.75)), fill=DARK, outline=BLACK,
              width=P.stroke(0.02))                        # axe head, edge into the trunk


def draw_place(P):
    """2: the box above the stump, arrow down."""
    d = P.d
    device(P, 0.16, 0.06, 0.78, 0.30)
    d.rectangle([P.p(0.78, 0.16), P.p(0.87, 0.20)], fill=BLACK)   # crank stub
    P.circle(0.88, 0.18, 0.025, BLACK)
    d.rectangle([P.p(0.44, 0.37), P.p(0.56, 0.50)], fill=BLACK)   # arrow shaft
    d.polygon(P.pts((0.32, 0.50), (0.68, 0.50), (0.50, 0.63)), fill=BLACK)
    stump(P, cx=0.50, top_v=0.74, bot_v=0.94, hw=0.22)


def draw_crank(P):
    """3: the box on the stump, crank turning."""
    d = P.d
    stump(P, cx=0.46, top_v=0.58, bot_v=0.82, hw=0.24)
    device(P, 0.14, 0.28, 0.72, 0.54)
    P.line((0.72, 0.41), (0.80, 0.41), k=0.03)              # axle
    P.line((0.80, 0.41), (0.88, 0.32), k=0.03)              # crank arm
    P.circle(0.88, 0.32, 0.035, BLACK)                     # handle
    cx, cy = P.p(0.80, 0.41)                               # rotation arrow
    R = 0.13 * P.s
    d.arc((cx - R, cy - R, cx + R, cy + R), start=-75, end=105, fill=BLACK, width=P.stroke(0.028))
    a = math.radians(105)
    arrowhead(P, 0.80 + 0.13 * math.cos(a), 0.41 + 0.13 * math.sin(a) * (P.s / P.bh),
              -math.sin(a), math.cos(a), 0.085)


def draw_talk(P):
    """4: a head in profile speaks; sound waves; a speech bubble saying AI."""
    d = P.d
    bx0, by0 = P.p(0.46, 0.04)                             # bubble
    bx1, by1 = P.p(0.98, 0.26)
    d.rounded_rectangle((bx0, by0, bx1, by1), radius=int((bx1 - bx0) * 0.22),
                        fill=WHITE, outline=BLACK, width=P.stroke(0.03))
    P.line((0.57, 0.26), (0.69, 0.26), k=0.04, fill=WHITE)  # open the border for the tail
    P.line((0.57, 0.26), (0.51, 0.36), k=0.03)
    P.line((0.69, 0.26), (0.51, 0.36), k=0.03)
    d.text(((bx0 + bx1) / 2, (by0 + by1) / 2), "AI", fill=BLACK,
           font=font(int((by1 - by0) * 0.62)), anchor="mm")
    head = [
        (0.30, 0.98), (0.30, 0.78),                        # back of the neck
        (0.20, 0.70), (0.14, 0.58), (0.14, 0.44), (0.19, 0.33),   # back of the skull
        (0.27, 0.25), (0.38, 0.21), (0.50, 0.21), (0.59, 0.26), (0.64, 0.36),   # crown, forehead
        (0.62, 0.46),                                      # brow
        (0.70, 0.54), (0.65, 0.58),                        # nose
        (0.67, 0.62), (0.60, 0.64),                        # upper lip
        (0.66, 0.68), (0.60, 0.72),                        # open mouth
        (0.64, 0.78), (0.56, 0.84),                        # chin
        (0.48, 0.90), (0.48, 0.98),                        # front of the neck
    ]
    d.polygon(P.pts(*head), fill=BLACK)
    P.circle(0.54, 0.42, 0.028, WHITE)                     # eye
    mx, my = P.p(0.68, 0.66)                               # sound waves
    for k in (0.10, 0.17, 0.24):
        R = k * P.s
        d.arc((mx - R, my - R, mx + R, my + R), start=-45, end=45, fill=BLACK, width=P.stroke(0.03))


# --------------------------------------------------------------------- layout

def snap_to_levels(img):
    """Nearest of the panel's four grey levels for every pixel; the soft
    edges from downsampling become one-step grey fringes, which is as close
    to anti-aliasing as the panel gets."""
    lut = [min(LEVELS, key=lambda lv: abs(lv - v)) for v in range(256)]
    return img.point(lut)


def main():
    img = Image.new("L", (W * SS, H * SS), LIGHT)         # grey ground, white cards
    d = ImageDraw.Draw(img)
    m = int(W * SS * 0.04)          # outer margin
    g = int(W * SS * 0.035)         # gutter between cards
    cols, rows = (2, 2) if PORTRAIT else (4, 1)
    pw = (W * SS - 2 * m - (cols - 1) * g) // cols
    ph = (H * SS - 2 * m - (rows - 1) * g) // rows
    for i, fn in enumerate((draw_chop, draw_place, draw_crank, draw_talk)):
        c, r = i % cols, i // cols
        x0, y0 = m + c * (pw + g), m + r * (ph + g)
        fn(Panel(d, (x0, y0, x0 + pw, y0 + ph), i + 1))
    out = snap_to_levels(img.resize((W, H), Image.LANCZOS))
    out.save(OUT)
    print(f"wrote {OUT}  ({W}x{H}, {'portrait' if PORTRAIT else 'landscape'}, 4 grey levels)")


if __name__ == "__main__":
    main()
