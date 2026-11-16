"""Helpers shared by the full page captures of Chrome and Firefox.

The JavaScript expressions return JSON, read the same way by every browser.
"""

from collections import namedtuple
import json
import logging
import math
import struct
import time
import uuid

from ..exceptions import CaptureTooLargeError

logger = logging.getLogger(__name__)

DEFAULT_MAX_PIXELS = 100_000_000
FULL_PAGE_PROFILES = ('fast', 'balanced', 'robust')
FIXED_ELEMENT_MODES = ('auto', 'preserve', 'first', 'last', 'hide')

# A fixed or sticky element that is too small to be seen is ignored. Its
# content counts, since it can overflow an element that has no size itself.
_IS_OVERLAY_JS = '''
const isOverlay = (element) => {
    const style = getComputedStyle(element);
    if (style.position !== 'fixed' && style.position !== 'sticky') {
        return false;
    }
    if (style.display === 'none' || style.visibility === 'hidden') {
        return false;
    }
    const rect = element.getBoundingClientRect();
    return Math.max(rect.width, element.scrollWidth) >= 4
        && Math.max(rect.height, element.scrollHeight) >= 4;
};
'''

OVERLAY_COUNT_JS = '''
(() => {
    %s
    return JSON.stringify(
        [...document.querySelectorAll('*')].filter(isOverlay).length
    );
})()
''' % _IS_OVERLAY_JS

_SHOW_OVERLAYS_JS = '''
(() => {
    %s
    const [key, mode, first, last] = %%s;
    const registry = window[key]
        || (window[key] = {entries: [], seen: new WeakSet()});
    const properties = ['opacity', 'transition', 'position', 'top', 'bottom'];

    // The page is scanned again for every tile: scrolling can load new
    // elements or make an existing one fixed.
    for (const element of document.querySelectorAll('*')) {
        if (registry.seen.has(element) || !isOverlay(element)) continue;
        registry.seen.add(element);
        const saved = {};
        for (const property of properties) {
            saved[property] = [
                element.style.getPropertyValue(property),
                element.style.getPropertyPriority(property),
            ];
        }
        const rect = element.getBoundingClientRect();
        const topDistance = Math.abs(rect.top);
        const bottomDistance = Math.abs(innerHeight - rect.bottom);
        const sticky = getComputedStyle(element).position === 'sticky';
        if (sticky && mode === 'auto') {
            // A sticky element stays where it is in the flow of the page.
            element.style.setProperty('position', 'relative', 'important');
            element.style.setProperty('top', 'auto', 'important');
            element.style.setProperty('bottom', 'auto', 'important');
        }
        registry.entries.push({
            element, saved, sticky, bottom: bottomDistance + 1 < topDistance,
        });
    }

    for (const {element, saved, sticky, bottom} of registry.entries) {
        let visible;
        if (mode === 'hide') visible = false;
        else if (mode === 'first') visible = first;
        else if (mode === 'last') visible = last;
        else if (sticky) visible = true;
        else visible = bottom ? last : first;
        // Unlike `visibility`, `opacity` cannot be overridden by a
        // descendant.
        for (const [property, value] of
             [['opacity', '0'], ['transition', 'none']]) {
            if (!visible) {
                element.style.setProperty(property, value, 'important');
            } else if (saved[property][0]) {
                element.style.setProperty(property, ...saved[property]);
            } else {
                element.style.removeProperty(property);
            }
        }
    }
    return JSON.stringify(null);
})()
''' % _IS_OVERLAY_JS

_RESTORE_OVERLAYS_JS = '''
(() => {
    const key = %s;
    for (const {element, saved} of (window[key] || {entries: []}).entries) {
        for (const [property, [value, priority]] of Object.entries(saved)) {
            if (value) element.style.setProperty(property, value, priority);
            else element.style.removeProperty(property);
        }
    }
    delete window[key];
    return JSON.stringify(null);
})()
'''

# The elements that cross the row just above `seam`, remembered with their
# position in the page. Fixed and sticky elements, and the elements inside
# of them, do not move with the page: they are left out.
_MARK_ANCHORS_JS = '''
(() => {
    const [key, seam] = %s;
    const isFloating = (element) => {
        for (; element && element !== document.body;
             element = element.parentElement) {
            const position = getComputedStyle(element).position;
            if (position === 'fixed' || position === 'sticky') return true;
        }
        return false;
    };
    const row = Math.min(innerHeight - 1, Math.max(0, seam - scrollY - 1));
    const anchors = [];
    for (const x of [0.08, 0.2, 0.33, 0.45, 0.55, 0.67, 0.8, 0.92]) {
        const elements = document.elementsFromPoint(innerWidth * x, row);
        for (const element of elements) {
            if (element === document.documentElement
                || element === document.body) break;
            if (isFloating(element)) continue;
            if (!anchors.some(anchor => anchor.element === element)) {
                const top = element.getBoundingClientRect().top + scrollY;
                anchors.push({element, top});
            }
            break;
        }
    }
    window[key] = anchors;
    return JSON.stringify(anchors.length);
})()
'''

_ANCHOR_SHIFTS_JS = '''
JSON.stringify((window[%s] || [])
    .filter(anchor => anchor.element.isConnected)
    .map(anchor =>
        anchor.element.getBoundingClientRect().top + scrollY - anchor.top))
'''

_FORGET_ANCHORS_JS = '''
JSON.stringify(%s.map(key => delete window[key]))
'''

_UNCHECKED_SEAMS = {
    'no anchor': (
        '%s: the full page image was joined from several screenshots, and '
        'the joins at %s could not be checked, as too few elements of the '
        'page were found there. The image may be wrong there if the page '
        'moved while it was captured.'
    ),
    'uneven': (
        '%s: the page moved unevenly while it was captured, near the joins '
        'between screenshots at %s. The image may be wrong there.'
    ),
    'moving': (
        '%s: the page kept moving while it was captured, near the joins '
        'between screenshots at %s. The image may be wrong there.'
    ),
}

_JPEG_FRAME_MARKERS = {
    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
}

# One part of the final image: `content_height` rows of a tile, from its
# row `crop_top`, pasted at the row `paste_y` of the image. The tile was
# `capture_height` rows high, captured from the row `capture_y` of the page.
TileSegment = namedtuple(
    'TileSegment',
    'capture_y capture_height paste_y content_height crop_top',
    defaults=[0],
)


def show_overlays_js(key, mode, first, last):
    """Return the script showing fixed and sticky elements as `mode` asks.

    `first` and `last` tell whether the tile about to be captured is the
    first or the last one. The elements found are remembered under
    `window[key]` until `restore_overlays_js()` is run.
    """
    return _SHOW_OVERLAYS_JS % json.dumps([key, mode, first, last])


def restore_overlays_js(key):
    """Return the script undoing every change made by `show_overlays_js()`.
    """
    return _RESTORE_OVERLAYS_JS % json.dumps(key)


def page_shift(shifts):
    """Return how far the page moved, from how far its anchors moved.

    Returns None if it cannot be told: no anchor, or anchors that moved in
    different ways. A single anchor that disagrees with at least two others
    is ignored: it is an element that moves by itself, such as an animated
    picture. A single anchor cannot confirm that the page moved.
    """
    best = []
    for shift in shifts:
        group = [other for other in shifts if abs(other - shift) <= 1]
        if len(group) > len(best):
            best = group
    if not best or len(shifts) - len(best) > (len(best) > 1):
        return None
    shift = round(sorted(best)[len(best) // 2])
    if len(best) == 1 and shift:
        return None
    return shift


class SeamChecker:
    """Keeps the tiles of a full page capture in line with the page.

    Before a tile is captured, the elements that cross its bottom row, the
    seam with the next tile, are marked. Before the next tile, they are
    read again: if they all moved the same way, so did the page, and the
    next tile will start that much higher or lower. When it cannot be told,
    nothing is changed, and a warning will be logged by `warn()`.

    `evaluate` returns the value of a JavaScript expression that returns
    JSON. `sleep` waits for a number of milliseconds.
    """

    poll_ms = 60
    settle_timeout = 2

    def __init__(self, evaluate, sleep):
        self.evaluate = evaluate
        self.sleep = sleep
        key = '__h2i_seam_%s' % uuid.uuid4().hex
        # The anchors of the seams above and below the current tile.
        self.above, self.below = key + '_above', key + '_below'
        self.has_above = False
        self.problem = None
        self.unchecked = {problem: [] for problem in _UNCHECKED_SEAMS}

    def _shifts(self, key):
        return self.evaluate(_ANCHOR_SHIFTS_JS % json.dumps(key))

    def shift(self):
        """Return how far the page moved since the seam above the current
        tile was marked, or 0 if it cannot be told or if there is no such
        seam.

        If the page moved, it is first given the time to stop moving.
        """
        self.problem = None
        if not self.has_above:
            return 0
        shifts = self._shifts(self.above)
        shift = page_shift(shifts)
        if any(abs(value) >= 0.5 for value in shifts):
            deadline = time.monotonic() + self.settle_timeout
            while True:
                self.sleep(self.poll_ms)
                shifts = self._shifts(self.above)
                previous, shift = shift, page_shift(shifts)
                if shift == previous:
                    break
                if time.monotonic() > deadline:
                    self.problem = 'moving'
                    return 0
        if shift is None:
            self.problem = 'uneven' if len(shifts) > 1 else 'no anchor'
            logger.debug('Seam not checked (%s): %s', self.problem, shifts)
            return 0
        if shift:
            logger.debug('The page moved by %d px: %s', shift, shifts)
        return shift

    def mark(self, seam):
        """Mark the anchors of the seam below the current tile, at the row
        `seam` of the page."""
        self.evaluate(_MARK_ANCHORS_JS % json.dumps([self.below, seam]))

    def moved(self):
        """Return True if the page moved since `mark()`."""
        shifts = self._shifts(self.below)
        if page_shift(shifts) in (0, None):
            return False
        logger.debug('The page moved during the capture: %s', shifts)
        return True

    def next_tile(self, row):
        """Move on to the next tile, whose top will be at `row` in the
        image."""
        if self.problem:
            self.unchecked[self.problem].append(row)
        self.above, self.below = self.below, self.above
        self.has_above = True

    def forget(self):
        """Remove the anchors from the page."""
        keys = [self.above, self.below]
        self.evaluate(_FORGET_ANCHORS_JS % json.dumps(keys))

    def warn(self, name):
        """Log a warning for each kind of seam that could not be checked."""
        for problem, rows in self.unchecked.items():
            if rows:
                logger.warning(
                    _UNCHECKED_SEAMS[problem],
                    name,
                    ', '.join('%d px' % row for row in rows),
                )


def output_format_from_filename(filename):
    """Return the format of the image named `filename`, 'png' or 'jpeg'."""
    name = filename.lower()
    if name.endswith('.png'):
        return 'png'
    if name.endswith(('.jpg', '.jpeg')):
        return 'jpeg'
    raise ValueError(
        'full_page output_file must end with .png, .jpg, or .jpeg '
        f'(got {filename!r})'
    )


def _is_positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_viewport(width, height):
    if not (_is_positive_int(width) and _is_positive_int(height)):
        raise ValueError(
            'full_page size must contain two strictly positive integers '
            f'(got {(width, height)!r})'
        )


def validate_full_page_profile(profile):
    if profile not in FULL_PAGE_PROFILES:
        raise ValueError(
            'full_page_profile must be one of: '
            f'{", ".join(sorted(FULL_PAGE_PROFILES))} (got {profile!r})'
        )


def validate_fixed_element_mode(mode):
    if mode not in FIXED_ELEMENT_MODES:
        raise ValueError(
            'full_page_fixed_elements must be one of: '
            f'{", ".join(sorted(FIXED_ELEMENT_MODES))} (got {mode!r})'
        )


def validate_max_pixels(max_pixels):
    if max_pixels is not None and not _is_positive_int(max_pixels):
        raise ValueError(
            'full_page_max_pixels must be a strictly positive integer or '
            f'None (got {max_pixels!r})'
        )


def validate_stability_timeout(timeout):
    if timeout is None:
        return
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not 0 < timeout < math.inf
    ):
        raise ValueError(
            'full_page_stability_timeout must be a strictly positive finite '
            f'float or None (got {timeout!r})'
        )


def enforce_pixel_budget(width, height, max_pixels):
    """Raise CaptureTooLargeError if the image would have more than
    `max_pixels` pixels, instead of saving a cut image."""
    if max_pixels is not None and width * height > max_pixels:
        raise CaptureTooLargeError(
            'Full-page capture would contain '
            f'{width * height:,} pixels ({width}x{height}), exceeding '
            f'full_page_max_pixels={max_pixels:,}. Increase the limit or '
            'set it to None to disable this safety check.'
        )


def next_tile_height(y, total_height, tile_height, viewport_height,
                     fixed_elements):
    """Return the height of the tile starting at `y`."""
    remaining = total_height - y
    if fixed_elements != 'last':
        return min(tile_height, remaining)
    # The final tile is the whole last viewport, so that an element fixed at
    # its top is part of the image.
    if remaining <= viewport_height:
        return remaining
    return min(tile_height, remaining - viewport_height)


def image_dimensions(data):
    """Return the width and height of a PNG or JPEG image, without an
    imaging library."""
    if data.startswith(b'\x89PNG'):
        return struct.unpack('>II', data[16:24])

    # The segments of a JPEG image follow each other, each made of a marker
    # and of its length, until the one that gives the size of the image.
    offset = 2
    while data[offset + 1] not in _JPEG_FRAME_MARKERS:
        offset += 2 + struct.unpack('>H', data[offset + 2:offset + 4])[0]
    height, width = struct.unpack('>HH', data[offset + 5:offset + 9])
    return width, height


def import_pyvips_for_stitching():
    """Import the optional dependency only when tiling is actually required.
    """
    try:
        import pyvips
    except ImportError:
        raise ImportError(
            'pyvips is required to assemble a tiled full-page capture. '
            'Install it with: pip install "html2image[full-page]"'
        ) from None
    return pyvips


def _has_regular_tile_heights(tile_plan):
    """Return True if all the tiles but the last have the same height, and
    the last one is not higher."""
    heights = [segment.content_height for segment in tile_plan]
    return (
        len(set(heights[:-1])) <= 1
        and heights[-1] <= heights[0]
    )


def stitch_tiles(tile_bytes, tile_plan, total_width, total_height,
                 output_format):
    """Join the tiles captured by the browser into one image."""
    pyvips = import_pyvips_for_stitching()
    png = output_format == 'png'

    tiles = []
    for encoded_tile, segment in zip(tile_bytes, tile_plan):
        tile = pyvips.Image.new_from_buffer(
            encoded_tile, '', access='sequential'
        ).crop(0, segment.crop_top, total_width, segment.content_height)
        if png and tile.bands == 3:
            tile = tile.bandjoin(255)
        elif not png and tile.bands == 4:
            tile = tile.flatten(background=[255, 255, 255])
        tiles.append(tile)

    if _has_regular_tile_heights(tile_plan):
        # arrayjoin uses cells of the same size, so the only padding is
        # after the last tile, which is cropped.
        canvas = pyvips.Image.arrayjoin(tiles, across=1)
        canvas = canvas.crop(0, 0, total_width, total_height)
    else:
        # With fixed_elements='last', a short tile can come before the last
        # one, where arrayjoin would add padding: each tile is inserted at
        # its place instead.
        if png:
            canvas = pyvips.Image.black(total_width, total_height, bands=4)
        else:
            canvas = pyvips.Image.black(total_width, total_height, bands=3)
            canvas += 255
        for tile, segment in zip(tiles, tile_plan):
            canvas = canvas.insert(tile, 0, segment.paste_y)

    if png:
        return canvas.write_to_buffer('.png[compression=6]')
    return canvas.write_to_buffer('.jpg[Q=90]')
