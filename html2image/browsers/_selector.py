"""Helpers used to save an image of the element matching a CSS selector.

The JavaScript expressions return JSON, read the same way by every browser.
"""

import json
import math

# Returns the selectors that are not valid. Searching an empty fragment
# checks the syntax without depending on the content of the page.
_INVALID_SELECTORS_JS = '''
JSON.stringify(%s.filter(selector => {
    try {
        document.createDocumentFragment().querySelector(selector);
        return false;
    } catch (error) {
        return true;
    }
}))
'''

# Returns null if no element matches the selector, or the box of the first
# matching element, in page coordinates, with the size of the page.
#
# The ancestors of the element are scrolled so that it gets displayed, which
# also lets the page load what it only loads once visible. The page itself is
# then scrolled back: fixed elements would otherwise be drawn over an element
# taller than the viewport. The scroll positions of the ancestors before that
# are returned, to put them back after the capture with `_RESTORE_JS`.
#
# The size of the root element, the scroll position and the size of the
# viewport are only used by Firefox, on pages without doctype.
_ELEMENT_BOX_JS = '''
(async () => {
    const element = document.querySelector(%s);
    if (!element) return JSON.stringify(null);

    const scrolls = [];
    for (let node = element.parentElement; node; node = node.parentElement) {
        scrolls.push([node.scrollLeft, node.scrollTop]);
    }
    const [pageX, pageY] = [scrollX, scrollY];
    element.scrollIntoView(
        {block: 'center', inline: 'center', behavior: 'instant'}
    );
    await new Promise(
        done => requestAnimationFrame(() => requestAnimationFrame(done))
    );
    scrollTo({left: pageX, top: pageY, behavior: 'instant'});

    const rect = element.getBoundingClientRect();
    const page = document.scrollingElement || document.documentElement;
    const root = document.documentElement;
    return JSON.stringify({
        x: rect.x + scrollX,
        y: rect.y + scrollY,
        width: rect.width,
        height: rect.height,
        pageWidth: page.scrollWidth,
        pageHeight: page.scrollHeight,
        rootWidth: root.scrollWidth,
        rootHeight: root.scrollHeight,
        scrollX: scrollX,
        scrollY: scrollY,
        viewportWidth: visualViewport.width,
        viewportHeight: visualViewport.height,
        scrolls: scrolls,
    });
})()
'''

# Scrolls the ancestors of the element back to the positions returned by
# `_ELEMENT_BOX_JS`, so that each image shows the page as loaded.
_RESTORE_JS = '''
(() => {
    let node = document.querySelector(%s);
    for (const [left, top] of %s) {
        node = node?.parentElement;
        node?.scrollTo({left: left, top: top, behavior: 'instant'});
    }
    return JSON.stringify(null);
})()
'''

_SCROLL_JS = '''
(() => {
    scrollTo({left: %s, top: %s, behavior: 'instant'});
    return JSON.stringify([scrollX, scrollY]);
})()
'''


def invalid_selectors_js(selectors):
    """Return a JavaScript expression that finds the invalid selectors."""
    return _INVALID_SELECTORS_JS % json.dumps(selectors)


def element_box_js(selector):
    """Return a JavaScript expression that measures the `selector` element.
    """
    return _ELEMENT_BOX_JS % json.dumps(selector)


def restore_js(selector, box):
    """Return a JavaScript expression that scrolls the ancestors of the
    `selector` element back to where they were before `element_box_js()`.
    """
    return _RESTORE_JS % (json.dumps(selector), json.dumps(box['scrolls']))


def scroll_js(x, y):
    """Return a JavaScript expression that scrolls the page to (x, y).

    The expression returns the reached scroll position.
    """
    return _SCROLL_JS % (x, y)


def check_selectors(evaluate, selectors):
    """Raise ValueError if a selector is not valid.

    Only the browser knows which selectors it supports, so `evaluate` runs
    a JavaScript expression in the page and returns its value.
    """
    invalid = evaluate(invalid_selectors_js(selectors))
    if invalid:
        raise ValueError(f'"{invalid[0]}" is not a valid CSS selector.')


def element_clip(box, padding):
    """Turn the value of the `element_box_js()` expression into a clip.

    The clip is the area of the page, in whole pixels, that covers the
    element and `padding` pixels on each of its sides, without going past
    the edges of the page.

    Returns None if there is nothing to capture: no element, an element
    without size, or an element outside of the page.
    """
    if box is None or not box['width'] or not box['height']:
        return None

    left = max(0, math.floor(box['x'] - padding))
    top = max(0, math.floor(box['y'] - padding))
    right = min(
        box['pageWidth'], math.ceil(box['x'] + box['width'] + padding)
    )
    bottom = min(
        box['pageHeight'], math.ceil(box['y'] + box['height'] + padding)
    )
    if right <= left or bottom <= top:
        return None

    return {'x': left, 'y': top, 'width': right - left, 'height': bottom - top}


def _nearest_scroll(scroll, start, size, viewport):
    """Return the scroll position closest to `scroll` that shows the
    `size` pixels from `start`, on one axis.
    """
    return min(max(scroll, start + size - viewport), start)


def viewport_scroll(box, clip):
    """Return the scroll position of the page that shows all of `clip`.

    The page is scrolled as little as possible from its position in `box`,
    a value of the `element_box_js()` expression, so that it looks as
    loaded. Returns None if `clip` does not fit in the viewport.
    """
    width, height = box['viewportWidth'], box['viewportHeight']
    if clip['width'] > width or clip['height'] > height:
        return None

    return (
        _nearest_scroll(box['scrollX'], clip['x'], clip['width'], width),
        _nearest_scroll(box['scrollY'], clip['y'], clip['height'], height),
    )
