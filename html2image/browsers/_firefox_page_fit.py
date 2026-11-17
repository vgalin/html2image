"""Full page capture for Firefox, see `capture_full_page()`.

The viewport keeps the size given by the caller. Firefox captures the whole
page in one go when it can. Otherwise, the page is captured one viewport at
a time, and the tiles are joined.
"""

import base64
import logging
from pathlib import Path
import time
import uuid

from ._page_fit_common import (
    DEFAULT_MAX_PIXELS,
    OVERLAY_COUNT_JS,
    capture_tiles,
    enforce_format_limit,
    enforce_pixel_budget,
    image_dimensions,
    output_format_from_filename,
    restore_overlays_js,
    show_overlays_js,
    warn,
    window_height,
)
from .browser import needs_restart

logger = logging.getLogger(__name__)

_AUTO_PROBE_GROWTH_TRIGGER = 0.03
_DOCUMENT_DIMENSION_TOLERANCE_PX = 2

_STABILITY_POLL_MS = 300
_STABILITY_SETTLE_QUICK_S = 1.2
_STABILITY_DEADLINE_QUICK_S = 2.8
_STABILITY_MIN_QUICK_S = 1.8
_SETTLE_AFTER_WARMUP_S = 1.1
_DEADLINE_AFTER_WARMUP_S = 2.6
_MIN_AFTER_WARMUP_S = 1.5

_EXHAUST_SCROLL_WAIT_MS = 260
_EXHAUST_TRAVERSE_WAIT_MS = 120
_EXHAUST_SCROLL_MAX_ROUNDS = 18
_EXHAUST_SCROLL_STABLE_ROUNDS = 3
_STANDARD_SCROLL_STEPS = 8
_STANDARD_SCROLL_WAIT_MS = 130
_BOTTOM_PAINT_WAIT_MS = 180
_TILE_SCROLL_WAIT_MS = 120
# Firefox refuses to capture more pixels than this in width or in height,
# see `firefox_bidi.MAX_CAPTURE_SIZE`.
_DOCUMENT_CAPTURE_MAX_SIZE = 65535
_PRE_CAPTURE_SETTLE_MS = 150

# An SVG file has no body, and its root element has no offsetHeight.
_DOCUMENT_HEIGHT_JS = '''
JSON.stringify(Math.max(
    document.documentElement.scrollHeight,
    document.documentElement.offsetHeight || 0,
    document.documentElement.clientHeight,
    document.body ? document.body.scrollHeight : 0,
    document.body ? document.body.offsetHeight : 0,
    document.body ? document.body.clientHeight : 0
))
'''

_CONTENT_HEIGHT_JS = '''
JSON.stringify(Math.max(
    document.documentElement.scrollHeight,
    document.body ? document.body.scrollHeight : 0
))
'''

_MAX_SCROLL_JS = '''
JSON.stringify(Math.max(
    0,
    (document.scrollingElement || document.documentElement).scrollHeight
        - innerHeight
))
'''

_SCROLL_Y_JS = 'JSON.stringify(Math.max(0, Math.round(scrollY)))'

_SCROLL_JS = '''
(() => {
    scrollTo({left: 0, top: %d, behavior: 'instant'});
    return JSON.stringify(null);
})()
'''


def _capture(browser, origin, output_format='png'):
    """Return an image of the viewport or of the whole page, as `origin`
    asks, 'viewport' or 'document'."""
    response = browser._bidi_expect_ok(
        browser._bidi_send(
            'browsingContext.captureScreenshot',
            context=browser._context_id,
            origin=origin,
            format={'type': 'image/' + output_format},
        ),
        timeout=60,
    )
    return base64.b64decode(response['result']['data'])


def _scroll_to(browser, y):
    browser._evaluate(_SCROLL_JS % y)


def _sleep_ms(milliseconds):
    time.sleep(milliseconds / 1000)


def _read_document_height(browser, viewport_height):
    """Return the height of the page, at least that of the viewport."""
    return max(viewport_height, browser._evaluate(_DOCUMENT_HEIGHT_JS))


def _measure_stable_document_height(browser, width, viewport_height,
                                    max_pixels, deadline, settle_after,
                                    min_duration):
    """Return the height of the page once its layout has settled."""
    start = time.monotonic()
    last_height = None
    stable_ticks = 0
    while True:
        height = _read_document_height(browser, viewport_height)
        enforce_pixel_budget(width, height, max_pixels)
        if height == last_height:
            stable_ticks += 1
        else:
            stable_ticks = 0
        last_height = height

        elapsed = time.monotonic() - start
        if elapsed >= max(settle_after, min_duration) and stable_ticks >= 3:
            return height
        if elapsed >= deadline:
            return height
        _sleep_ms(_STABILITY_POLL_MS)


def _lazy_growth_probe(browser, width, viewport_height, max_pixels):
    """Return how much the page grew, as a fraction of its height, once
    scrolled near its bottom."""
    before = browser._evaluate(_CONTENT_HEIGHT_JS)
    max_scroll = browser._evaluate(_MAX_SCROLL_JS)
    if max_scroll < 160:
        return 0
    for ratio in (0.75, 0.97):
        _scroll_to(browser, int(max_scroll * ratio))
        _sleep_ms(220)
    after = browser._evaluate(_CONTENT_HEIGHT_JS)
    enforce_pixel_budget(width, max(viewport_height, after), max_pixels)
    _scroll_to(browser, 0)
    _sleep_ms(80)
    return (after - before) / before


def _standard_lazy_warmup(browser, width, viewport_height, max_pixels):
    max_scroll = browser._evaluate(_MAX_SCROLL_JS)
    if max_scroll <= 0:
        return
    for step in range(1, _STANDARD_SCROLL_STEPS + 1):
        _scroll_to(browser, int(max_scroll * step / _STANDARD_SCROLL_STEPS))
        _sleep_ms(_STANDARD_SCROLL_WAIT_MS)
        height = browser._evaluate(_CONTENT_HEIGHT_JS)
        enforce_pixel_budget(width, max(viewport_height, height), max_pixels)
    _scroll_to(browser, 0)
    _sleep_ms(80)


def _exhaust_lazy_warmup(browser, viewport_height, width, max_pixels):
    max_scroll = browser._evaluate(_MAX_SCROLL_JS)
    if max_scroll <= 0:
        return
    best_height = browser._evaluate(_CONTENT_HEIGHT_JS)
    enforce_pixel_budget(width, max(viewport_height, best_height), max_pixels)
    scanned_to = 0
    stable_hits = 0
    for _ in range(_EXHAUST_SCROLL_MAX_ROUNDS):
        # The first round shows every part of the page. Later rounds only
        # show the content added since, so that endless feeds end.
        before_scroll = browser._evaluate(_MAX_SCROLL_JS)
        target = max(0, scanned_to - viewport_height)
        step = max(1, int(viewport_height * 0.85))
        while target < before_scroll:
            _scroll_to(browser, target)
            _sleep_ms(_EXHAUST_TRAVERSE_WAIT_MS)
            target += step
        _scroll_to(browser, before_scroll)
        _sleep_ms(_EXHAUST_SCROLL_WAIT_MS)
        scanned_to = before_scroll

        height = browser._evaluate(_CONTENT_HEIGHT_JS)
        enforce_pixel_budget(width, max(viewport_height, height), max_pixels)
        scroll = browser._evaluate(_MAX_SCROLL_JS)
        if height > best_height + 4 or scroll > before_scroll + 4:
            best_height = max(best_height, height)
            stable_hits = 0
        else:
            stable_hits += 1
            if stable_hits >= _EXHAUST_SCROLL_STABLE_ROUNDS:
                break
    _scroll_to(browser, 0)
    _sleep_ms(120)


def _bottom_paint_warmup(browser):
    max_scroll = browser._evaluate(_MAX_SCROLL_JS)
    if max_scroll <= 0:
        return
    for ratio in (0.33, 0.66, 0.9, 1.0):
        _scroll_to(browser, int(max_scroll * ratio))
        _sleep_ms(_BOTTOM_PAINT_WAIT_MS)
    _scroll_to(browser, 0)
    _sleep_ms(90)


def _settled_document_height(browser, width, viewport_height, profile,
                             stability_timeout, max_pixels):
    """Return the height of the page, once the content it loads when
    scrolled is loaded, as `profile` asks."""
    if profile == 'fast':
        return _read_document_height(browser, viewport_height)

    height = _measure_stable_document_height(
        browser, width, viewport_height, max_pixels,
        deadline=stability_timeout or _STABILITY_DEADLINE_QUICK_S,
        settle_after=_STABILITY_SETTLE_QUICK_S,
        min_duration=_STABILITY_MIN_QUICK_S,
    )
    growth = _lazy_growth_probe(browser, width, viewport_height, max_pixels)
    if profile == 'balanced':
        _standard_lazy_warmup(browser, width, viewport_height, max_pixels)
        if growth >= _AUTO_PROBE_GROWTH_TRIGGER:
            _standard_lazy_warmup(
                browser, width, viewport_height, max_pixels
            )
    else:
        # Robust also loads the content that already has its size, which
        # the growth of the page cannot tell.
        _exhaust_lazy_warmup(browser, viewport_height, width, max_pixels)
        _bottom_paint_warmup(browser)

    if profile == 'robust' or growth >= _AUTO_PROBE_GROWTH_TRIGGER:
        height = _measure_stable_document_height(
            browser, width, viewport_height, max_pixels,
            deadline=stability_timeout or _DEADLINE_AFTER_WARMUP_S,
            settle_after=_SETTLE_AFTER_WARMUP_S,
            min_duration=_MIN_AFTER_WARMUP_S,
        )
    return height


def _show_overlays(browser, key, mode, first, last):
    browser._evaluate(show_overlays_js(key, mode, first, last))


def _try_document_capture(browser, width, height, output_format):
    """Return an image of the whole page, or None if it does not have the
    size of the page, for example on a page without doctype, where
    Firefox only captures the root element."""
    image = _capture(browser, 'document', output_format)
    actual_width, actual_height = image_dimensions(image)
    if (actual_width != width
            or abs(actual_height - height) > _DOCUMENT_DIMENSION_TOLERANCE_PX):
        logger.debug(
            'Firefox captured the page as %dx%d pixels, instead of %dx%d.',
            actual_width, actual_height, width, height,
        )
        return None
    return image


class _Tiles:
    """The tiles of a page in Firefox, see `capture_tiles()`.

    Firefox captures the whole viewport, and the tile is cut out of it.
    """

    name = 'Firefox'

    def __init__(self, browser, width, viewport_height):
        self.browser = browser
        self.width = width
        self.viewport_height = self.tile_height = viewport_height

    def evaluate(self, expression):
        return self.browser._evaluate(expression)

    def sleep(self, milliseconds):
        _sleep_ms(milliseconds)

    def scroll_to(self, y):
        _scroll_to(self.browser, y)

    def settle(self):
        _sleep_ms(_TILE_SCROLL_WAIT_MS)

    def measure(self):
        return _read_document_height(self.browser, self.viewport_height)

    def viewport(self):
        """Return the scroll position and the height of the viewport."""
        return self.browser._evaluate(_SCROLL_Y_JS), self.viewport_height

    def shorten(self, top, height, scroll_y):
        """Return the height of the tile at `top`, when the page cannot be
        scrolled to show it: the tile stops at the bottom of the viewport,
        or there is no tile if its top is not shown.
        """
        if not scroll_y <= top < scroll_y + self.viewport_height:
            return 0
        return scroll_y + self.viewport_height - top

    def capture(self, top, height, scroll_y, visible):
        """Return the tile, with the place and the height of what was
        captured, and the first row of the tile that is kept."""
        tile = _capture(self.browser, 'viewport')
        return tile, scroll_y, self.viewport_height, top - scroll_y


def capture_full_page(browser, output_path, output_file, width,
                      viewport_height, stability_timeout=None,
                      profile='robust', fixed_elements='auto',
                      max_pixels=DEFAULT_MAX_PIXELS):
    """Save an image of the whole page loaded by `browser`.

    The viewport keeps its size: `width` is also the width of the image,
    and `viewport_height` changes how the page is laid out and loads its
    content, but the image will be as high as the page. The options are
    those of `Html2Image.screenshot()`, already checked.
    """
    output_format = output_format_from_filename(output_file)
    overlay_key = '__h2i_page_fit_%s' % uuid.uuid4().hex
    restart = False
    try:
        _sleep_ms(250)
        total_height = _settled_document_height(
            browser, width, viewport_height, profile, stability_timeout,
            max_pixels,
        )
        total_height, messages = window_height(
            browser._evaluate, total_height, viewport_height, output_file
        )
        enforce_pixel_budget(width, total_height, max_pixels)
        enforce_format_limit(width, total_height, output_format)
        _scroll_to(browser, 0)
        _sleep_ms(_PRE_CAPTURE_SETTLE_MS)

        overlay_count = browser._evaluate(OVERLAY_COUNT_JS)
        image = None
        # Fixed elements are only shown once in tiles.
        force_tiling = (
            total_height > viewport_height
            and fixed_elements in ('auto', 'last')
            and overlay_count > 0
        )
        too_large = max(width, total_height) > _DOCUMENT_CAPTURE_MAX_SIZE
        if not force_tiling and not too_large:
            if fixed_elements == 'hide' and overlay_count > 0:
                _show_overlays(
                    browser, overlay_key, 'hide', first=True, last=True
                )
            image = _try_document_capture(
                browser, width, total_height, output_format
            )
            browser._evaluate(restore_overlays_js(overlay_key))

        if image is None:
            # The page may have changed while it was captured in one go.
            total_height = _read_document_height(browser, viewport_height)
            enforce_pixel_budget(width, total_height, max_pixels)
            image, tile_messages = capture_tiles(
                _Tiles(browser, width, viewport_height),
                fixed_elements, output_format, max_pixels, output_file,
            )
            messages += tile_messages
        Path(output_path, output_file).write_bytes(image)
        for message in messages:
            warn(message)
    except Exception as error:
        restart = needs_restart(error)
        raise
    finally:
        # The page is put back as it was, if it can be: the browser may be
        # lost, and the error that stopped the capture is the one to raise.
        # A browser that will be restarted is left as it is: after a delay
        # passed, each cleanup would wait as long.
        for cleanup in () if restart else (
            lambda: browser._evaluate(restore_overlays_js(overlay_key)),
            lambda: _scroll_to(browser, 0),
        ):
            try:
                cleanup()
            except Exception:
                pass
