"""Helpers shared by the full page captures of Chrome and Firefox.

The JavaScript expressions return JSON, read the same way by every browser.
"""

from collections import namedtuple
import json
import logging
import math
import struct
import sys
import time
import uuid
import warnings

from ..exceptions import (
    BrowserError,
    CaptureTooLargeError,
    FullPageWarning,
    Html2ImageError,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_PIXELS = 100_000_000
FULL_PAGE_PROFILES = ('fast', 'balanced', 'robust')
FIXED_ELEMENT_MODES = ('auto', 'preserve', 'first', 'last', 'hide')
# Tries to capture a tile while the page moves or does not show it.
_TILE_ATTEMPTS = 4
# The JPEG images written by pyvips cannot be wider or higher than this.
_JPEG_MAX_SIZE = 65_500

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

# Fixed and sticky elements, and the elements inside of them, do not move
# with the page.
_IS_FLOATING_JS = '''
const floating = new Map();
const isFloating = (element) => {
    if (!element || element === document.documentElement) return false;
    if (!floating.has(element)) {
        const position = getComputedStyle(element).position;
        floating.set(element, position === 'fixed'
            || position === 'sticky' || isFloating(element.parentElement));
    }
    return floating.get(element);
};
'''

# The anchors of the seam at the row `seam` of the page: in each of a few
# columns of the viewport, the top or bottom edge of an element that is the
# closest above the seam, within a viewport. Content that moves between them
# and the seam cannot be seen, so they are as close to it as can be. Floating
# elements are left out.
#
# When a single element is found, as when a block as wide as the page ends
# just above the seam, backup anchors are found the same way, above it and
# outside of it. The outermost box that shares its edge would move with
# it, so they are found outside of that box.
_MARK_ANCHORS_JS = '''
(() => {
    const [key, backupKey, seam] = %%s;
    %s
    const columns = [0.08, 0.2, 0.33, 0.45, 0.55, 0.67, 0.8, 0.92]
        .map(x => x * innerWidth);
    const root = document.body || document.documentElement;
    // An element that is not shown has no box.
    const shown = [...root.querySelectorAll('*')]
        .map(element => [element, element.getBoundingClientRect()])
        .filter(([element, rect]) => rect.width || rect.height);
    const find = (limit, outside) => {
        const closest = columns.map(() => null);
        for (const [element, rect] of shown) {
            if (outside && outside.contains(element)) continue;
            for (const edge of ['top', 'bottom']) {
                const position = rect[edge] + scrollY;
                if (position > limit || position <= seam - innerHeight) {
                    continue;
                }
                columns.forEach((x, column) => {
                    if (x < rect.left || x >= rect.right) return;
                    // On a tie, the element inside of the other one is kept.
                    if (closest[column]
                        && closest[column].position > position
                        || isFloating(element)) return;
                    closest[column] = {element, edge, position};
                });
            }
        }
        // An element is only counted once.
        return closest.filter((anchor, column) => anchor
            && closest.findIndex(other => other
                && other.element === anchor.element) === column);
    };
    const anchors = find(seam);
    let backups = [];
    if (anchors.length === 1) {
        const [{element, edge, position}] = anchors;
        let box = element;
        while (box.parentElement && box.parentElement !== root
               && Math.abs(box.parentElement.getBoundingClientRect()[edge]
                           + scrollY - position) <= 0.5) {
            box = box.parentElement;
        }
        backups = find(position - 1, box);
    }
    window[key] = anchors;
    window[backupKey] = backups;
    return JSON.stringify([anchors.length, backups.length]);
})()
''' % _IS_FLOATING_JS

# How far the anchors moved. An anchor that is no longer shown, or that has
# become fixed, does not tell anything about the page.
_ANCHOR_SHIFTS_JS = '''
(() => {
    %s
    return JSON.stringify((window[%%s] || [])
        .filter(({element}) => element.isConnected && !isFloating(element))
        .map(anchor => [anchor, anchor.element.getBoundingClientRect()])
        .filter(([anchor, rect]) => rect.width || rect.height)
        .map(([anchor, rect]) =>
            rect[anchor.edge] + scrollY - anchor.position));
})()
''' % _IS_FLOATING_JS

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


def page_shift(shifts, backups=()):
    """Return how far the page moved, from how far its anchors moved.

    Returns None if it cannot be told: no anchor, or anchors that moved in
    different ways. The page only moved if all its anchors agree. If the
    others did not move, a single anchor that moved is ignored: it is an
    element that moves by itself, such as an animated picture. A single
    anchor cannot tell by itself that the page moved: the backup anchors,
    found outside of it, must all have moved with it.
    """
    best = []
    for shift in shifts:
        group = [other for other in shifts if abs(other - shift) <= 1]
        if len(group) > len(best):
            best = group
    if not best:
        return None
    shift = round(sorted(best)[len(best) // 2])
    if len(shifts) - len(best) > (len(best) > 1 and shift == 0):
        return None
    if len(best) == 1 and shift and not (
        backups and all(abs(other - shifts[0]) <= 1 for other in backups)
    ):
        return None
    return shift


class SeamChecker:
    """Keeps the tiles of a full page capture in line with the page.

    Before a tile is captured, the elements just above its bottom row, the
    seam with the next tile, are marked. Before the next tile, they are
    read again: if they all moved the same way, so did the page, and the
    next tile will start that much higher or lower. When it cannot be told,
    nothing is changed, and `messages()` will tell where.

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
        # Whether the anchors of the seams above and below the current tile
        # moved unevenly while a tile was captured, see `moved()`, and the
        # top of the last tile in the image.
        self.uneven_above = self.uneven_below = False
        self.row = 0

    def _shifts(self, key):
        return self.evaluate(_ANCHOR_SHIFTS_JS % json.dumps(key))

    def _page_shift(self, key):
        """Return how far the page moved since the anchors `key` were
        marked, or None, and how far the anchors moved."""
        shifts = self._shifts(key)
        shift = page_shift(shifts)
        if shift is None and len(shifts) == 1:
            backups = self._shifts(key + '_backups')
            return page_shift(shifts, backups), shifts + backups
        return shift, shifts

    def shift(self, still=lambda: False):
        """Return how far the page moved since the seam above the current
        tile was marked, or 0 if it cannot be told or if there is no such
        seam.

        If the page moved, it is first given the time to stop moving. If
        no anchor was found, `still()` tells if nothing else shows that the
        page moved, and the seam is then taken as checked.
        """
        self.problem = 'uneven' if self.uneven_above else None
        if not self.has_above:
            return 0
        shift, shifts = self._page_shift(self.above)
        if any(abs(value) >= 0.5 for value in shifts):
            deadline = time.monotonic() + self.settle_timeout
            while True:
                self.sleep(self.poll_ms)
                previous = shift
                shift, shifts = self._page_shift(self.above)
                if shift == previous:
                    break
                if time.monotonic() > deadline:
                    self.problem = 'moving'
                    return 0
        if shift is None:
            if not shifts and still():
                logger.debug('No anchor at the seam, on a page that did '
                             'not move.')
                return 0
            self.problem = 'uneven' if len(shifts) > 1 else 'no anchor'
            logger.debug('Seam not checked (%s): %s', self.problem, shifts)
            return 0
        if shift:
            logger.debug('The page moved by %d px: %s', shift, shifts)
        return shift

    def mark(self, seam):
        """Mark the anchors of the seam below the current tile, at the row
        `seam` of the page."""
        self.evaluate(_MARK_ANCHORS_JS % json.dumps(
            [self.below, self.below + '_backups', seam]))
        self.uneven_below = False

    def moved(self):
        """Return True if the page moved since `mark()`.

        If only a part of the page moved, the tile is kept, but the seam
        will not be checked.
        """
        shift, shifts = self._page_shift(self.below)
        if shift is None and any(abs(value) >= 0.5 for value in shifts):
            logger.debug('The page moved unevenly during the capture: %s',
                         shifts)
            self.uneven_below = True
        if not shift:
            return False
        logger.debug('The page moved during the capture: %s', shifts)
        return True

    def next_tile(self, row):
        """Move on to the next tile, whose top will be at `row` in the
        image."""
        if self.problem:
            self.unchecked[self.problem].append(row)
        self.uneven_above, self.uneven_below = self.uneven_below, False
        self.row = row
        self.above, self.below = self.below, self.above
        self.has_above = True

    def forget(self):
        """Remove the anchors from the page."""
        keys = [self.above, self.below]
        keys += [key + '_backups' for key in keys]
        self.evaluate(_FORGET_ANCHORS_JS % json.dumps(keys))

    def messages(self, name):
        """Return a warning for each kind of seam that could not be
        checked, in the image named `name`."""
        # The last tile has no seam below it: if the page moved unevenly
        # while it was captured, the seam above it is not checked.
        uneven = self.unchecked['uneven']
        if self.uneven_above and self.row and self.row not in uneven:
            uneven.append(self.row)
        return [
            _UNCHECKED_SEAMS[problem]
            % (name, ', '.join('%d px' % row for row in rows))
            for problem, rows in self.unchecked.items()
            if rows
        ]


def warn(message):
    """Give a FullPageWarning, shown where html2image was called."""
    # The warning is shown at the line of the first frame that is not in
    # the package.
    frame, level = sys._getframe(), 1
    while frame and frame.f_globals.get('__name__', '').startswith(
            'html2image.'):
        frame, level = frame.f_back, level + 1
    warnings.warn(message, FullPageWarning, stacklevel=level)


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


def enforce_format_limit(width, height, output_format):
    """Raise CaptureTooLargeError if the image would be too large to be
    saved in its format, before capturing it."""
    if output_format == 'jpeg' and max(width, height) > _JPEG_MAX_SIZE:
        raise CaptureTooLargeError(
            f'Full-page capture would be {width}x{height} pixels, but a '
            f'JPEG image cannot be larger than {_JPEG_MAX_SIZE:,} pixels '
            'in width or in height. Save it as a PNG image instead.'
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
    try:
        return _stitch_tiles(
            pyvips, tile_bytes, tile_plan, total_width, total_height,
            output_format,
        )
    except pyvips.Error as error:
        raise Html2ImageError(
            f'The screenshots of the page could not be joined: {error}'
        ) from error


def _stitch_tiles(pyvips, tile_bytes, tile_plan, total_width, total_height,
                  output_format):
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


def capture_tiles(page, fixed_elements, output_format, max_pixels,
                  output_file):
    """Capture the page one viewport at a time, and join the tiles.

    Returns the image, and the warnings to give once it is saved. `page`
    does what depends on the browser: it has the `name` of the
    browser, the `width` of the image, the `viewport_height`, the
    `tile_height`, and the methods `evaluate()`, `sleep()`, `scroll_to()`,
    `settle()`, `measure()`, `viewport()`, `shorten()` and `capture()`.
    """
    # Fail before capturing every tile when the optional stitcher is absent.
    import_pyvips_for_stitching()
    width = page.width
    overlay_key = None
    if fixed_elements != 'preserve':
        overlay_key = '__h2i_page_fit_%s' % uuid.uuid4().hex
    seams = SeamChecker(page.evaluate, page.sleep)

    plan, tiles = [], []
    # The top of the next tile, in the layout of the page when the previous
    # tile was captured, and in the image. Where the page was last scrolled
    # to, and its height when the previous tile was captured.
    y = image_y = requested = 0
    previous_height = None

    def still():
        # The page kept its height, and it stopped where it was asked to.
        scroll_y, shown_height = page.viewport()
        expected = min(requested, max(0, total_height - shown_height))
        logger.debug(
            'Page of %s px, then %d px, scrolled to %s px for %s px.',
            previous_height, total_height, scroll_y, expected,
        )
        return (
            total_height == previous_height and abs(scroll_y - expected) < 1
        )

    try:
        page.scroll_to(requested)
        page.settle()
        while True:
            for attempt in range(_TILE_ATTEMPTS):
                # Scrolling can change the height of a page (a header that
                # collapses, content loaded on demand). The tiles follow the
                # page as it is now, not as it was when first measured.
                total_height = page.measure()
                enforce_pixel_budget(width, total_height, max_pixels)
                enforce_format_limit(width, total_height, output_format)
                top = y + seams.shift(still)
                if top >= total_height:
                    break
                height = next_tile_height(
                    top, total_height, page.tile_height,
                    page.viewport_height, fixed_elements,
                )
                # The page may not stop where it was asked to, for example
                # if it changed while it was scrolled.
                scroll_y, shown_height = page.viewport()
                visible = (
                    scroll_y <= top and top + height <= scroll_y + shown_height
                )
                if not visible and attempt < _TILE_ATTEMPTS - 1:
                    requested = top
                    page.scroll_to(requested)
                    page.settle()
                    continue
                if not visible:
                    height = page.shorten(top, height, scroll_y)

                if overlay_key is not None:
                    page.evaluate(show_overlays_js(
                        overlay_key, fixed_elements,
                        first=not tiles, last=top + height == total_height,
                    ))
                seams.mark(top + height)
                tile, capture_y, capture_height, crop_top = page.capture(
                    top, height, scroll_y, visible
                )
                # If the page moved while the tile was captured, the tile
                # may show it before or after it moved.
                if not seams.moved():
                    break
                page.settle()
            else:
                seams.problem = 'moving'
            if top >= total_height:
                break

            size = image_dimensions(tile)
            if size != (width, capture_height):
                raise BrowserError(
                    '%s returned a tile of %dx%d pixels, instead of %dx%d.'
                    % (page.name, *size, width, capture_height)
                )
            tiles.append(tile)
            plan.append(TileSegment(
                capture_y, capture_height, image_y, height, crop_top
            ))
            seams.next_tile(image_y)
            previous_height = total_height
            y = requested = top + height
            image_y += height
            if y >= total_height:
                break
            page.scroll_to(requested)
            page.settle()
    finally:
        try:
            seams.forget()
        finally:
            if overlay_key is not None:
                page.evaluate(restore_overlays_js(overlay_key))

    image = stitch_tiles(tiles, plan, width, image_y, output_format)
    return image, seams.messages(output_file)
