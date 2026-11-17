"""Full page capture for Chrome and Edge, see `capture_full_page()`.

The viewport keeps the size given by the caller. A page that fits in one
capture is captured in one go. A longer page is captured one viewport at a
time, and the tiles are joined.
"""

import base64
import logging
import math
from pathlib import Path
import time
import uuid

from ._page_fit_common import (
    DEFAULT_MAX_PIXELS,
    OVERLAY_COUNT_JS,
    capture_tiles,
    enforce_format_limit,
    enforce_pixel_budget,
    output_format_from_filename,
    restore_overlays_js,
    show_overlays_js,
    warn,
)
from ..exceptions import BrowserError

logger = logging.getLogger(__name__)

# Higher pages are captured in tiles. Chrome does not refuse a larger
# capture, but its image is wrong beyond 16,384 pixels, see
# `chrome_cdp.MAX_CAPTURE_SIZE`.
_NATIVE_CAPTURE_MAX_HEIGHT = 16_000
_TARGET_TILE_PIXELS = 4_000_000
_MIN_TILE_HEIGHT = 1_024
_MAX_TILE_HEIGHT = 8_000

_STABILITY_POLL_MS = 300
_STABILITY_STABLE_TICKS = 3
_DEFAULT_STABILITY_TIMEOUT = 2.8
_BALANCED_STEPS = 8
_BALANCED_SCROLL_WAIT_MS = 130
_ROBUST_TRAVERSE_WAIT_MS = 120
_ROBUST_SCROLL_WAIT_MS = 260
_ROBUST_MAX_ROUNDS = 18
_ROBUST_STABLE_ROUNDS = 3
_TILE_SCROLL_SETTLE_MS = 140
_AUTO_PROBE_GROWTH_TRIGGER = 0.03

# An SVG file has no body, and its root element has no offsetHeight.
_CONTENT_HEIGHT_JS = '''
Math.max(
    document.documentElement.scrollHeight,
    document.documentElement.offsetHeight || 0,
    document.body ? document.body.scrollHeight : 0,
    document.body ? document.body.offsetHeight : 0
)
'''

_DOCUMENT_HEIGHT_JS = '''
JSON.stringify(Math.max(
    %s,
    document.documentElement.clientHeight,
    document.body ? document.body.clientHeight : 0
))
''' % _CONTENT_HEIGHT_JS

_MAX_SCROLL_JS = 'JSON.stringify(Math.max(0, %s - innerHeight))' % (
    _CONTENT_HEIGHT_JS
)


def _send(browser, method, timeout=30, **params):
    return browser._wait_for_result(
        browser.cdp_send(method, **params), timeout=timeout
    )


def _sleep_ms(browser, milliseconds):
    browser._evaluate(
        "new Promise(done => setTimeout(() => done('null'), %d))"
        % milliseconds
    )


def _scroll_to(browser, y):
    browser._evaluate(
        "(scrollTo({left: 0, top: %d, behavior: 'instant'}), 'null')" % y
    )


def _wait_for_paint(browser):
    browser._evaluate(
        "new Promise(done => requestAnimationFrame("
        "() => requestAnimationFrame(() => done('null'))))"
    )


def _content_height(browser):
    return browser._evaluate('JSON.stringify(%s)' % _CONTENT_HEIGHT_JS)


def _measure_once(browser, viewport_height):
    """Return the height of the page, at least that of the viewport."""
    content = _send(browser, 'Page.getLayoutMetrics')['result']
    return max(
        viewport_height,
        browser._evaluate(_DOCUMENT_HEIGHT_JS),
        math.ceil(content['cssContentSize']['height']),
    )


def _measure_stable_height(browser, viewport_height, timeout):
    """Return the height of the page once its layout has settled."""
    deadline = time.monotonic() + timeout
    last_height = None
    stable_ticks = 0
    while True:
        height = _measure_once(browser, viewport_height)
        if height == last_height:
            stable_ticks += 1
        else:
            stable_ticks = 0
        last_height = height

        if (stable_ticks >= _STABILITY_STABLE_TICKS
                or time.monotonic() >= deadline):
            return height
        _sleep_ms(browser, _STABILITY_POLL_MS)


def _lazy_growth_probe(browser):
    """Return how much the page grew, as a fraction of its height, once
    scrolled near its bottom."""
    before = _content_height(browser)
    max_scroll = browser._evaluate(_MAX_SCROLL_JS)
    if max_scroll < 160:
        return 0
    for ratio in (0.75, 0.97):
        _scroll_to(browser, int(max_scroll * ratio))
        _sleep_ms(browser, 220)
    after = _content_height(browser)
    _scroll_to(browser, 0)
    _sleep_ms(browser, 80)
    return (after - before) / before


def _scroll_through_page(browser):
    max_scroll = browser._evaluate(_MAX_SCROLL_JS)
    if max_scroll <= 0:
        return
    for step in range(1, _BALANCED_STEPS + 1):
        _scroll_to(browser, int(max_scroll * step / _BALANCED_STEPS))
        _sleep_ms(browser, _BALANCED_SCROLL_WAIT_MS)
    _scroll_to(browser, 0)
    _sleep_ms(browser, 80)


def _exhaust_lazy_content(browser, viewport_height, width, max_pixels):
    best_height = _content_height(browser)
    enforce_pixel_budget(width, max(viewport_height, best_height), max_pixels)
    scanned_to = 0
    stable_rounds = 0

    for _ in range(_ROBUST_MAX_ROUNDS):
        max_scroll = browser._evaluate(_MAX_SCROLL_JS)
        if max_scroll <= 0:
            break

        # The first round shows every part of the page. Later rounds only
        # show the content added since, so that endless feeds end.
        target = max(0, scanned_to - viewport_height)
        step = max(1, int(viewport_height * 0.85))
        while target < max_scroll:
            _scroll_to(browser, target)
            _sleep_ms(browser, _ROBUST_TRAVERSE_WAIT_MS)
            target += step
        _scroll_to(browser, max_scroll)
        _sleep_ms(browser, _ROBUST_SCROLL_WAIT_MS)
        scanned_to = max_scroll

        height = _content_height(browser)
        enforce_pixel_budget(width, max(viewport_height, height), max_pixels)
        if height > best_height + 4:
            best_height = height
            stable_rounds = 0
        else:
            stable_rounds += 1
            if stable_rounds >= _ROBUST_STABLE_ROUNDS:
                break

    _scroll_to(browser, 0)
    _sleep_ms(browser, 120)


def _settled_document_height(browser, width, viewport_height, profile,
                             stability_timeout, max_pixels):
    """Return the height of the page, once the content it loads when
    scrolled is loaded, as `profile` asks."""
    if profile == 'fast':
        height = _measure_once(browser, viewport_height)
        enforce_pixel_budget(width, height, max_pixels)
        return height

    timeout = stability_timeout or _DEFAULT_STABILITY_TIMEOUT
    height = _measure_stable_height(browser, viewport_height, timeout)
    enforce_pixel_budget(width, height, max_pixels)

    # Balanced shows the page at a few places. Robust shows every part of
    # it, which also loads the content that already has its size.
    growth = _lazy_growth_probe(browser)
    enforce_pixel_budget(
        width, _measure_once(browser, viewport_height), max_pixels
    )
    if profile == 'robust':
        _exhaust_lazy_content(browser, viewport_height, width, max_pixels)
    else:
        _scroll_through_page(browser)
        if growth >= _AUTO_PROBE_GROWTH_TRIGGER:
            _scroll_through_page(browser)

    height = _measure_stable_height(browser, viewport_height, timeout)
    enforce_pixel_budget(width, height, max_pixels)
    return height


def _choose_tile_height(width, viewport_height):
    target = _TARGET_TILE_PIXELS // width
    adaptive = max(_MIN_TILE_HEIGHT, min(_MAX_TILE_HEIGHT, target))
    # A tile is captured as shown in the viewport, see `_Tiles`.
    return min(adaptive, viewport_height)


def _capture(browser, y, width, height, output_format, beyond_viewport):
    """Return an image of the rows `y` to `y + height` of the page.

    With `beyond_viewport`, they do not need to be in the viewport.
    """
    params = {}
    if output_format == 'jpeg':
        params['quality'] = 90
    response = _send(
        browser,
        'Page.captureScreenshot',
        timeout=80,
        format=output_format,
        fromSurface=True,
        captureBeyondViewport=beyond_viewport,
        omitBackground=output_format == 'png',
        clip={'x': 0, 'y': y, 'width': width, 'height': height, 'scale': 1},
        **params,
    )
    data = response['result'].get('data')
    if not data:
        raise BrowserError('No screenshot data returned by Chromium CDP')
    return base64.b64decode(data)


def _show_overlays(browser, key, mode, first, last):
    browser._evaluate(show_overlays_js(key, mode, first, last))


def _restore_overlays(browser, key):
    if key is not None:
        browser._evaluate(restore_overlays_js(key))


def _settle(browser, profile):
    _wait_for_paint(browser)
    if profile != 'fast':
        _sleep_ms(browser, _TILE_SCROLL_SETTLE_MS)


class _Tiles:
    """The tiles of a page in Chrome, see `capture_tiles()`.

    The tiles are captured as they are shown in the viewport. Capturing
    beyond it would show the page a viewport of 1 x 1 pixel for a moment,
    and some pages lay themselves out again when this happens.
    """

    name = 'Chromium'

    def __init__(self, browser, width, viewport_height, profile):
        self.browser = browser
        self.width = width
        self.viewport_height = viewport_height
        self.tile_height = _choose_tile_height(width, viewport_height)
        self.profile = profile

    def evaluate(self, expression):
        return self.browser._evaluate(expression)

    def sleep(self, milliseconds):
        _sleep_ms(self.browser, milliseconds)

    def scroll_to(self, y):
        _scroll_to(self.browser, y)

    def settle(self):
        _settle(self.browser, self.profile)

    def measure(self):
        return _measure_once(self.browser, self.viewport_height)

    def viewport(self):
        """Return the scroll position and the height of the viewport."""
        return self.browser._evaluate('JSON.stringify([scrollY, innerHeight])')

    def shorten(self, top, height, scroll_y):
        """Return the height of the tile at `top`, when the page cannot be
        scrolled to show it."""
        logger.debug('Capturing the tile at %d px beyond the viewport.', top)
        return height

    def capture(self, top, height, scroll_y, visible):
        """Return the tile, with the place and the height of what was
        captured, and the first row of the tile that is kept."""
        tile = _capture(
            self.browser, top, self.width, height, 'png',
            beyond_viewport=not visible,
        )
        return tile, top, height, 0


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
    transparent_background = False
    hidden_registry = None
    try:
        _sleep_ms(browser, 250)
        total_height = _settled_document_height(
            browser, width, viewport_height, profile, stability_timeout,
            max_pixels,
        )
        enforce_format_limit(width, total_height, output_format)
        _scroll_to(browser, 0)
        overlay_count = browser._evaluate(OVERLAY_COUNT_JS)

        if output_format == 'png':
            _send(
                browser,
                'Emulation.setDefaultBackgroundColorOverride',
                color={'r': 0, 'g': 0, 'b': 0, 'a': 0},
            )
            transparent_background = True

        if fixed_elements == 'hide':
            hidden_registry = '__h2i_page_fit_%s' % uuid.uuid4().hex
            _show_overlays(
                browser, hidden_registry, 'hide', first=True, last=True
            )
            _wait_for_paint(browser)

        # Fixed elements are only shown once in tiles.
        force_tiled = (
            total_height > viewport_height
            and overlay_count > 0
            and fixed_elements in ('auto', 'last')
        )
        messages = []
        if total_height <= _NATIVE_CAPTURE_MAX_HEIGHT and not force_tiled:
            # Capturing beyond the viewport sends the page resize events, see
            # `_Tiles`. A page that fits in the viewport does not need it.
            image = _capture(
                browser, 0, width, total_height, output_format,
                beyond_viewport=total_height > viewport_height,
            )
        else:
            image, messages = capture_tiles(
                _Tiles(browser, width, viewport_height, profile),
                fixed_elements, output_format, max_pixels, output_file,
            )
        Path(output_path, output_file).write_bytes(image)
        for message in messages:
            warn(message)
    finally:
        # The page is put back as it was, if it can be: the browser may be
        # lost, and the error that stopped the capture is the one to raise.
        cleanups = [
            lambda: _scroll_to(browser, 0),
            lambda: _restore_overlays(browser, hidden_registry),
        ]
        if transparent_background:
            cleanups.append(lambda: _send(
                browser, 'Emulation.setDefaultBackgroundColorOverride'
            ))
        for cleanup in cleanups:
            try:
                cleanup()
            except Exception:
                pass
