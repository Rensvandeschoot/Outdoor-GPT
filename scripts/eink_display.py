"""
One-screen e-ink renderer for OutdoorGPT recipe mode.

Renders a finished recipe onto a Waveshare 7.5" (800x480) e-Paper HAT so the
cook can read it hands-free while the food is on the fire. The panel is
bistable: once drawn, the image stays put with the power off, so nobody has to
keep cranking just to hold the recipe on screen.

Design goals
------------
* Never crash the voice agent. Every hardware / library problem is logged and
  swallowed; the conversation keeps going even with no panel attached.
* One screen only. The recipe prompt already asks the model to keep answers
  short, but we still auto-shrink the font until the whole thing fits 800x480 -
  there is no "page 2" a cook could scroll to without power.
* Off the hot path. The ~6 s SPI refresh runs in a daemon thread; if a newer
  recipe arrives while one is still drawing, the newest one wins.

Only the driver import and Pillow import happen lazily inside the methods, so
importing this module on a dev machine (or a Pi without the panel) is harmless.

Requires, on the Pi only:
    * Pillow            (pip install pillow)
    * waveshare_epd     (the Waveshare e-Paper Python library, module
                         `waveshare_epd.epd7in5_V2` on the import path)
"""

import os
import threading

# Panel geometry (Waveshare 7.5" V2).
EPD_WIDTH = 800
EPD_HEIGHT = 480

MARGIN = 16          # px kept clear on every side
LINE_SPACING = 1.18  # baseline-to-baseline as a multiple of the font size
MAX_FONT = 28        # largest body font we try, px
MIN_FONT = 13        # smallest we shrink to before truncating
TITLE_BUMP = 3       # the dish title is this many px larger than the body

# Candidate TTF fonts, in order of preference. If none exist we fall back to
# Pillow's built-in bitmap font (readable, just not as pretty).
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]
_FONT_CANDIDATES_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _first_existing(paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return None


class EinkRecipeDisplay:
    """Lazily-initialised, fail-safe renderer for the recipe screen."""

    def __init__(self, verbose=False):
        self.verbose = verbose
        self._epd = None            # waveshare EPD instance, or None until first draw
        self._Image = None
        self._ImageDraw = None
        self._ImageFont = None
        self._font_path = _first_existing(_FONT_CANDIDATES)
        self._font_path_bold = _first_existing(_FONT_CANDIDATES_BOLD) or self._font_path
        self._first_draw = True
        self._init_failed = False   # once True we stop touching the hardware
        self._font_cache = {}       # (size, bold) -> font object
        self._lock = threading.Lock()
        self._pending = None        # newest text waiting to be drawn
        self._worker = None

    # ------------------------------------------------------------------ API

    def render_async(self, text):
        """Queue a recipe to be drawn, and return immediately.

        Only the most recent text matters: if a draw is already running, the new
        text replaces whatever was waiting, so the screen always ends on the
        latest recipe.
        """
        if self._init_failed or not text:
            return
        with self._lock:
            self._pending = text
            if self._worker is not None and self._worker.is_alive():
                return  # the running worker will pick up self._pending
            self._worker = threading.Thread(target=self._drain, daemon=True)
            self._worker.start()

    def clear(self):
        """Blank the panel. Optional; not used by default (see full_reset)."""
        if self._init_failed:
            return
        try:
            self._ensure_ready()
            self._epd.init()
            self._epd.Clear()
            self._epd.sleep()
            self._first_draw = False
        except Exception as e:            # pragma: no cover - hardware only
            self._log(f"clear failed: {e}")

    # ------------------------------------------------------------- internals

    def _log(self, msg):
        if self.verbose:
            print(f"[eink] {msg}")

    def _drain(self):
        """Worker loop: draw the newest pending text until the queue is empty."""
        while True:
            with self._lock:
                text = self._pending
                self._pending = None
                if text is None:
                    return
            try:
                self._ensure_ready()
            except Exception as e:
                # Import / construct failed -> no usable panel. Stop trying so we
                # don't burn ~6 s per turn failing for the rest of the session.
                self._log(f"panel unavailable, disabling e-ink for this session: {e}")
                self._init_failed = True
                return
            try:
                self._render_now(text)
            except Exception as e:
                # A transient draw error: log it but stay enabled; the next
                # recipe may well succeed.
                self._log(f"render failed (staying enabled): {e}")

    def _ensure_ready(self):
        """Import Pillow + the driver and construct the EPD. Raises on failure."""
        if self._Image is None:
            from PIL import Image, ImageDraw, ImageFont
            self._Image, self._ImageDraw, self._ImageFont = Image, ImageDraw, ImageFont
        if self._epd is None:
            from waveshare_epd import epd7in5_V2
            self._epd = epd7in5_V2.EPD()
            self._first_draw = True
            self._log("panel object created")

    def _load_font(self, size, bold=False):
        key = (size, bold)
        if key in self._font_cache:
            return self._font_cache[key]
        path = self._font_path_bold if bold else self._font_path
        if path:
            font = self._ImageFont.truetype(path, size)
        else:
            font = self._ImageFont.load_default()
        self._font_cache[key] = font
        return font

    def _text_width(self, draw, s, font):
        """Pixel width of `s`, across Pillow versions."""
        try:
            return draw.textlength(s, font=font)
        except AttributeError:
            pass
        try:
            return font.getlength(s)
        except AttributeError:
            bbox = draw.textbbox((0, 0), s, font=font)
            return bbox[2] - bbox[0]

    def _wrap_block(self, draw, text, font, max_width):
        """Word-wrap one logical line to a pixel width. Blank line stays blank."""
        if not text.strip():
            return [""]
        words = text.split()
        lines, cur = [], ""
        for w in words:
            trial = w if not cur else cur + " " + w
            if self._text_width(draw, trial, font) <= max_width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    def _normalise(self, text):
        """Screen-friendly cleanup: keep line breaks, drop markdown / emoji noise."""
        import re
        text = text.replace("*", "").replace("#", "").replace("`", "")
        text = re.sub(r"[ \t]+", " ", text)              # collapse spaces within a line
        text = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", text)  # cap blank runs at one
        emoji = re.compile(
            "[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U0001F1E0-\U0001F1FF]+"
        )
        text = emoji.sub("", text)
        return [ln.rstrip() for ln in text.strip().split("\n")]

    def _layout(self, draw, raw_lines, size, max_width):
        """Wrap the whole recipe at a given body font size.

        Returns (items, total_height) where items is a list of
        (text, font, line_height). The first non-empty line is treated as the
        dish title: bold and a few px larger.
        """
        body = self._load_font(size, bold=False)
        title_size = size + TITLE_BUMP
        title = self._load_font(title_size, bold=True)

        items = []
        title_used = False
        for ln in raw_lines:
            is_title = (not title_used) and ln.strip() != ""
            font = title if is_title else body
            fsize = title_size if is_title else size
            line_h = int(fsize * LINE_SPACING)
            for wrapped in self._wrap_block(draw, ln, font, max_width):
                items.append((wrapped, font, line_h))
            if is_title:
                title_used = True
        total = sum(h for (_t, _f, h) in items)
        return items, total

    def _render_now(self, text):
        Image, ImageDraw = self._Image, self._ImageDraw
        max_width = EPD_WIDTH - 2 * MARGIN
        max_height = EPD_HEIGHT - 2 * MARGIN
        raw_lines = self._normalise(text)

        img = Image.new("1", (EPD_WIDTH, EPD_HEIGHT), 255)  # 255 = white
        draw = ImageDraw.Draw(img)

        # Shrink the font until the whole recipe fits one screen.
        items = None
        size = MAX_FONT
        while size >= MIN_FONT:
            candidate, total = self._layout(draw, raw_lines, size, max_width)
            if total <= max_height:
                items = candidate
                break
            size -= 1

        # Even at the smallest size it overflows: keep what fits, add a marker.
        if items is None:
            size = MIN_FONT
            candidate, _ = self._layout(draw, raw_lines, size, max_width)
            kept, used = [], 0
            for it in candidate:
                if used + it[2] > max_height - int(MIN_FONT * LINE_SPACING):
                    break
                kept.append(it)
                used += it[2]
            marker = self._load_font(MIN_FONT)
            kept.append(("[...]", marker, int(MIN_FONT * LINE_SPACING)))
            items = kept
            self._log("recipe longer than one screen; truncated with a marker")

        y = MARGIN
        for wrapped, font, line_h in items:
            if wrapped:
                draw.text((MARGIN, y), wrapped, font=font, fill=0)  # 0 = black
            y += line_h

        self._epd.init()                 # wake from deep sleep (safe every draw)
        if self._first_draw:
            self._epd.Clear()            # one clean sweep on the very first draw
            self._first_draw = False
        self._epd.display(self._epd.getbuffer(img))
        try:
            self._epd.sleep()            # bistable: image holds with the power off
        except Exception:
            pass
        self._log(f"drew recipe at {size}px in {len(items)} lines")


# Manual smoke test on the Pi:  python3 eink_display.py
if __name__ == "__main__":
    sample = (
        "Foil-pack trout & potatoes\n"
        "Time: 25 min\n"
        "Ingredients:\n"
        "- 1 trout, cleaned\n"
        "- 1 potato, thinly sliced\n"
        "- 1 knob butter\n"
        "- a few sprigs wild thyme\n"
        "- salt, pepper\n"
        "Steps:\n"
        "1. Lay fish and potato on a double sheet of foil, butter and thyme on top, season.\n"
        "2. Fold into a sealed packet.\n"
        "3. Set on hot embers, not open flame, for 10 min.\n"
        "4. Flip; cook another 8-10 min.\n"
        "5. Open carefully; done when the fish flakes and the potato is tender."
    )
    disp = EinkRecipeDisplay(verbose=True)
    disp.render_async(sample)
    if disp._worker:
        disp._worker.join()
