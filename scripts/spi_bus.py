"""One lock for the SPI bus.

The e-ink panel and the audio HAT's three APA102 LEDs share SPI0: same MOSI,
same SCLK. Only the panel uses a chip select, so anything the LEDs write while
the panel is mid-transfer arrives at the panel as command bytes and corrupts
the drawing. Both take this lock around their writes so their turns never
overlap.

Held for the length of a whole panel refresh, which is several seconds. That
is deliberate: a paused LED animation is harmless, a corrupted recipe is not.
"""

import threading

# Re-entrant so a caller that already holds it can nest without deadlocking.
LOCK = threading.RLock()
