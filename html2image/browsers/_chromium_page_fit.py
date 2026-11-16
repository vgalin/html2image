"""Chromium full-page capture using a stable, caller-defined viewport.

The layout viewport is never resized to the document. Short documents use one
native CDP capture; long documents are captured in bounded regions and stitched.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..exceptions import BrowserError
from ._page_fit_common import (
    DEFAULT_MAX_PIXELS,
    OVERLAY_COUNT_JS,
    SeamChecker,
    TileSegment,
    enforce_pixel_budget,
    image_dimensions,
    import_pyvips_for_stitching,
    next_tile_height,
    output_format_from_filename,
    restore_overlays_js,
    show_overlays_js,
    stitch_tiles,
    validate_fixed_element_mode,
    validate_full_page_profile,
    validate_max_pixels,
    validate_stability_timeout,
    validate_viewport,
)

logger = logging.getLogger(__name__)

# This is a strategy threshold, not a document limit. Larger images are tiled.
_NATIVE_CAPTURE_MAX_HEIGHT = 16_000
_TARGET_TILE_PIXELS = 4_000_000
_MIN_TILE_HEIGHT = 1_024
_MAX_TILE_HEIGHT = 8_000

_STABILITY_POLL_MS = 300
_STABILITY_STABLE_TICKS = 3
_BALANCED_STEPS = 8
_BALANCED_SCROLL_WAIT_MS = 130
_ROBUST_TRAVERSE_WAIT_MS = 120
_ROBUST_SCROLL_WAIT_MS = 260
_ROBUST_MAX_ROUNDS = 18
_ROBUST_STABLE_ROUNDS = 3
_TILE_SCROLL_SETTLE_MS = 140
# Tries to capture a tile while the page moves or does not show it.
_TILE_ATTEMPTS = 4
_AUTO_PROBE_GROWTH_TRIGGER = 0.03

_DOM_DIMENSIONS_JS = r"""
(() => {
  const doc = document.documentElement;
  const body = document.body;
  return {
    width: Math.max(
      doc ? doc.scrollWidth : 0,
      doc ? doc.offsetWidth : 0,
      doc ? doc.clientWidth : 0,
      body ? body.scrollWidth : 0,
      body ? body.offsetWidth : 0,
      body ? body.clientWidth : 0
    ),
    height: Math.max(
      doc ? doc.scrollHeight : 0,
      doc ? doc.offsetHeight : 0,
      doc ? doc.clientHeight : 0,
      body ? body.scrollHeight : 0,
      body ? body.offsetHeight : 0,
      body ? body.clientHeight : 0
    )
  };
})()
""".strip()

_CONTENT_HEIGHT_JS = (
    "Math.max("
    "document.documentElement ? document.documentElement.scrollHeight : 0, "
    "document.documentElement ? document.documentElement.offsetHeight : 0, "
    "document.body ? document.body.scrollHeight : 0, "
    "document.body ? document.body.offsetHeight : 0)"
)

_MAX_SCROLL_JS = (
    "Math.max(0, " + _CONTENT_HEIGHT_JS + " - window.innerHeight)"
)


def _evaluate(browser: Any, expression: str, await_promise: bool = True) -> Any:
    command_id = browser.cdp_send(
        "Runtime.evaluate",
        expression=expression,
        returnByValue=True,
        awaitPromise=await_promise,
    )
    response = browser._wait_for_result(command_id)
    evaluation = response.get("result", {})
    if evaluation.get("exceptionDetails"):
        raise BrowserError(
            "JavaScript evaluation failed during full-page capture"
        )
    result = evaluation.get("result", {})
    return result.get("value")


def _send(browser: Any, method: str, timeout: int = 30, **params: Any) -> Dict[str, Any]:
    command_id = browser.cdp_send(method, **params)
    return browser._wait_for_result(command_id, timeout=timeout)


def _sleep_ms(browser: Any, milliseconds: int) -> None:
    _evaluate(
        browser,
        "new Promise(resolve => setTimeout(resolve, %d))" % milliseconds,
    )


def _scroll_to(browser: Any, y: int) -> None:
    _evaluate(
        browser,
        "window.scrollTo({left: 0, top: %d, behavior: 'instant'}); true"
        % int(y),
        await_promise=False,
    )


def _wait_for_paint(browser: Any) -> None:
    _evaluate(
        browser,
        "new Promise(resolve => requestAnimationFrame("
        "() => requestAnimationFrame(() => resolve(true))))",
    )


def _read_dimensions(browser: Any, viewport_height: int) -> Tuple[float, float]:
    dom = _evaluate(browser, _DOM_DIMENSIONS_JS) or {}
    metrics = _send(browser, "Page.getLayoutMetrics")
    content = metrics.get("result", {}).get("cssContentSize") or {}
    width = max(float(dom.get("width") or 0), float(content.get("width") or 0))
    height = max(
        float(viewport_height),
        float(dom.get("height") or 0),
        float(content.get("height") or 0),
    )
    return width, height


def _measure_once(browser: Any, viewport_height: int) -> int:
    _, height = _read_dimensions(browser, viewport_height)
    return max(viewport_height, int(math.ceil(height)))


def _measure_stable_height(
    browser: Any,
    viewport_height: int,
    timeout_s: float,
) -> int:
    """Return the height of the page once its layout has settled."""
    deadline = time.monotonic() + max(0.0, timeout_s)
    last_height: Optional[int] = None
    stable_ticks = 0

    while True:
        height = _measure_once(browser, viewport_height)
        if height == last_height:
            stable_ticks += 1
        else:
            stable_ticks = 0
        last_height = height

        if stable_ticks >= _STABILITY_STABLE_TICKS or time.monotonic() >= deadline:
            return height
        _sleep_ms(browser, _STABILITY_POLL_MS)


def _lazy_growth_probe(browser: Any) -> float:
    before = int(_evaluate(browser, _CONTENT_HEIGHT_JS) or 0)
    max_scroll = int(_evaluate(browser, _MAX_SCROLL_JS) or 0)
    if max_scroll < 160:
        return 0.0
    _scroll_to(browser, int(max_scroll * 0.75))
    _sleep_ms(browser, 220)
    _scroll_to(browser, int(max_scroll * 0.97))
    _sleep_ms(browser, 220)
    after = int(_evaluate(browser, _CONTENT_HEIGHT_JS) or 0)
    _scroll_to(browser, 0)
    _sleep_ms(browser, 80)
    return (after - before) / max(1.0, float(before))


def _scroll_through_page(browser: Any) -> None:
    max_scroll = int(_evaluate(browser, _MAX_SCROLL_JS) or 0)
    if max_scroll <= 0:
        return
    for step in range(1, _BALANCED_STEPS + 1):
        _scroll_to(browser, int(max_scroll * step / _BALANCED_STEPS))
        _sleep_ms(browser, _BALANCED_SCROLL_WAIT_MS)
    _scroll_to(browser, 0)
    _sleep_ms(browser, 80)


def _exhaust_lazy_content(
    browser: Any,
    viewport_height: int,
    width: int,
    max_pixels: Optional[int],
) -> None:
    best_height = int(_evaluate(browser, _CONTENT_HEIGHT_JS) or 0)
    enforce_pixel_budget(width, max(viewport_height, best_height), max_pixels)
    scanned_to = 0
    stable_rounds = 0

    for _ in range(_ROBUST_MAX_ROUNDS):
        max_scroll = int(_evaluate(browser, _MAX_SCROLL_JS) or 0)
        if max_scroll <= 0:
            break

        # The first round exposes every viewport-sized band. Later rounds only
        # scan newly appended content, which keeps infinite feeds bounded.
        start = max(0, scanned_to - viewport_height)
        step = max(1, int(viewport_height * 0.85))
        target = start
        while target < max_scroll:
            _scroll_to(browser, target)
            _sleep_ms(browser, _ROBUST_TRAVERSE_WAIT_MS)
            target += step
        _scroll_to(browser, max_scroll)
        _sleep_ms(browser, _ROBUST_SCROLL_WAIT_MS)
        scanned_to = max_scroll

        current_height = int(_evaluate(browser, _CONTENT_HEIGHT_JS) or 0)
        enforce_pixel_budget(
            width,
            max(viewport_height, current_height),
            max_pixels,
        )
        if current_height > best_height + 4:
            best_height = current_height
            stable_rounds = 0
        else:
            stable_rounds += 1
            if stable_rounds >= _ROBUST_STABLE_ROUNDS:
                break

    _scroll_to(browser, 0)
    _sleep_ms(browser, 120)


def _settled_document_height(
    browser: Any,
    width: int,
    viewport_height: int,
    profile: str,
    stability_timeout: Optional[float],
    max_pixels: Optional[int],
) -> int:
    if profile == "fast":
        height = _measure_once(browser, viewport_height)
        enforce_pixel_budget(width, height, max_pixels)
        return height

    timeout_s = stability_timeout if stability_timeout is not None else 2.8
    initial_height = _measure_stable_height(browser, viewport_height, timeout_s)
    enforce_pixel_budget(width, initial_height, max_pixels)

    # Balanced samples the page at fixed intervals. Robust exposes every
    # viewport-sized band, including lazy media with already-reserved geometry.
    growth = _lazy_growth_probe(browser)
    enforce_pixel_budget(
        width,
        _measure_once(browser, viewport_height),
        max_pixels,
    )
    if profile == "robust":
        _exhaust_lazy_content(browser, viewport_height, width, max_pixels)
    else:
        _scroll_through_page(browser)
        if growth >= _AUTO_PROBE_GROWTH_TRIGGER:
            _scroll_through_page(browser)

    final_height = _measure_stable_height(browser, viewport_height, timeout_s)
    enforce_pixel_budget(width, final_height, max_pixels)
    return final_height


def _choose_tile_height(width: int, viewport_height: int) -> int:
    target = int(_TARGET_TILE_PIXELS / max(1, width))
    adaptive = max(_MIN_TILE_HEIGHT, min(_MAX_TILE_HEIGHT, target))
    # Every tile must be fully paintable in the canonical viewport. Capturing a
    # taller clip can otherwise produce blank or stale regions below the fold.
    return max(1, min(adaptive, viewport_height))


def _set_transparent_background(browser: Any) -> None:
    _send(
        browser,
        "Emulation.setDefaultBackgroundColorOverride",
        color={"r": 0, "g": 0, "b": 0, "a": 0},
    )


def _restore_background(browser: Any) -> None:
    _send(browser, "Emulation.setDefaultBackgroundColorOverride")


def _capture_region(
    browser: Any,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    output_format: str,
    beyond_viewport=True,
) -> bytes:
    params: Dict[str, Any] = {
        "format": output_format,
        "fromSurface": True,
        "captureBeyondViewport": beyond_viewport,
        "omitBackground": output_format == "png",
        "clip": {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "scale": 1,
        },
    }
    if output_format == "jpeg":
        params["quality"] = 90
    response = _send(browser, "Page.captureScreenshot", timeout=80, **params)
    encoded = response.get("result", {}).get("data")
    if not encoded:
        raise BrowserError("No screenshot data returned by Chromium CDP")
    return base64.b64decode(encoded)


def _validate_capture(
    encoded: bytes,
    width: int,
    height: int,
    output_format: str,
) -> None:
    if output_format == "png" and not encoded.startswith(b"\x89PNG\r\n\x1a\n"):
        raise BrowserError("Chromium returned a non-PNG full-page capture")
    if output_format == "jpeg" and not encoded.startswith(b"\xff\xd8"):
        raise BrowserError("Chromium returned a non-JPEG full-page capture")
    actual = image_dimensions(encoded)
    if actual != (width, height):
        raise BrowserError(
            "Chromium returned %dx%d; expected %dx%d"
            % (actual[0], actual[1], width, height)
        )


def _overlay_registry_key() -> str:
    return "__h2i_page_fit_%s" % uuid.uuid4().hex


def _overlay_count(browser: Any) -> int:
    return int(_evaluate(browser, OVERLAY_COUNT_JS) or 0)


def _show_overlays(
    browser: Any,
    key: str,
    mode: str,
    first: bool,
    last: bool,
) -> None:
    _evaluate(browser, show_overlays_js(key, mode, first, last))


def _restore_overlays(browser: Any, key: Optional[str]) -> None:
    if key is not None:
        _evaluate(browser, restore_overlays_js(key))


def _settle(browser, profile):
    _wait_for_paint(browser)
    if profile != 'fast':
        _sleep_ms(browser, _TILE_SCROLL_SETTLE_MS)


def _is_visible(browser, top, height):
    """Return True if the rows `top` to `top + height` of the page are all
    in the viewport."""
    scroll_y, viewport_height = json.loads(
        _evaluate(browser, 'JSON.stringify([scrollY, innerHeight])')
    )
    return scroll_y <= top and top + height <= scroll_y + viewport_height


def _capture_tiled(
    browser,
    width,
    viewport_height,
    total_height,
    profile,
    fixed_elements,
    output_format,
    max_pixels,
    output_file,
):
    """Capture the page one viewport at a time, and join the tiles.

    The tiles are captured as they are shown in the viewport. Capturing
    beyond it would show the page a viewport of 1 x 1 pixel for a moment,
    and some pages lay themselves out again when this happens.
    """
    # Fail before capturing every tile when the optional stitcher is absent.
    import_pyvips_for_stitching()
    tile_height = _choose_tile_height(width, viewport_height)
    registry_key = None
    if fixed_elements != 'preserve':
        registry_key = _overlay_registry_key()
    seams = SeamChecker(
        lambda script: _evaluate(browser, script),
        lambda milliseconds: _sleep_ms(browser, milliseconds),
    )

    plan, tiles = [], []
    # The top of the next tile, in the layout of the page when the previous
    # tile was captured, and in the image.
    y = image_y = 0
    try:
        _scroll_to(browser, y)
        _settle(browser, profile)
        while True:
            for _ in range(_TILE_ATTEMPTS):
                # Scrolling can change the height of a page (a header that
                # collapses, content loaded on demand). The tiles follow the
                # page as it is now, not as it was when first measured.
                total_height = _measure_once(browser, viewport_height)
                enforce_pixel_budget(width, total_height, max_pixels)
                top = y + seams.shift()
                if top >= total_height:
                    break
                height = next_tile_height(
                    top, total_height, tile_height, viewport_height,
                    fixed_elements,
                )
                # The page may not stop where it was asked to, for example
                # if it changed while it was scrolled.
                visible = _is_visible(browser, top, height)
                if not visible:
                    _scroll_to(browser, top)
                    _settle(browser, profile)
                    continue

                if registry_key is not None:
                    _show_overlays(
                        browser,
                        registry_key,
                        fixed_elements,
                        first=not tiles,
                        last=top + height == total_height,
                    )
                seams.mark(top + height)
                tile = _capture_region(
                    browser,
                    x=0,
                    y=top,
                    width=width,
                    height=height,
                    output_format='png',
                    beyond_viewport=False,
                )
                # If the page moved while the tile was captured, the tile
                # may show it before or after it moved.
                if not seams.moved():
                    break
                _settle(browser, profile)
            else:
                if visible:
                    seams.problem = 'moving'
                else:
                    # The page could not be scrolled to show the tile.
                    logger.debug(
                        'Capturing the tile at %d px beyond the viewport.',
                        top,
                    )
                    tile = _capture_region(
                        browser,
                        x=0,
                        y=top,
                        width=width,
                        height=height,
                        output_format='png',
                    )
            if top >= total_height:
                break
            _validate_capture(tile, width, height, 'png')
            tiles.append(tile)
            plan.append(TileSegment(top, height, image_y, height))
            seams.next_tile(image_y)
            y = top + height
            image_y += height
            if y >= total_height:
                break
            _scroll_to(browser, y)
            _settle(browser, profile)
    finally:
        try:
            _scroll_to(browser, 0)
            seams.forget()
        finally:
            _restore_overlays(browser, registry_key)

    seams.warn(output_file)
    return stitch_tiles(tiles, plan, width, image_y, output_format)


def capture_full_page(
    browser: Any,
    output_path: str,
    output_file: str,
    width: int,
    viewport_height: int,
    stability_timeout: Optional[float] = None,
    profile: str = "robust",
    fixed_elements: str = "auto",
    max_pixels: Optional[int] = DEFAULT_MAX_PIXELS,
) -> None:
    """Capture the whole page loaded by ``browser``, without changing its
    layout viewport.

    ``width`` determines both responsive layout and output width.
    ``viewport_height`` affects layout, lazy loading and fixed elements, but the
    output grows to the measured document height. The stability timeout applies
    to each measurement pass; the ``fast`` profile intentionally ignores it.
    """
    width, viewport_height = validate_viewport(width, viewport_height)
    profile = validate_full_page_profile(profile)
    fixed_elements = validate_fixed_element_mode(fixed_elements)
    stability_timeout = validate_stability_timeout(stability_timeout)
    max_pixels = validate_max_pixels(max_pixels)
    output_format = output_format_from_filename(output_file)
    destination = Path(output_path) / output_file

    transparent_background = False
    hidden_registry: Optional[str] = None
    try:
        _sleep_ms(browser, 250)
        total_height = _settled_document_height(
            browser,
            width,
            viewport_height,
            profile,
            stability_timeout,
            max_pixels,
        )
        enforce_pixel_budget(width, total_height, max_pixels)
        _scroll_to(browser, 0)
        overlay_count = _overlay_count(browser)

        if output_format == "png":
            _set_transparent_background(browser)
            transparent_background = True

        if fixed_elements == "hide":
            hidden_registry = _overlay_registry_key()
            _show_overlays(
                browser,
                hidden_registry,
                "hide",
                first=True,
                last=True,
            )
            _wait_for_paint(browser)

        force_tiled = (
            total_height > viewport_height
            and overlay_count > 0
            and fixed_elements in {"auto", "last"}
        )
        # Chrome does not refuse a larger capture, but its image is wrong
        # beyond 16,384 pixels, see `chrome_cdp.MAX_CAPTURE_SIZE`.
        if total_height <= _NATIVE_CAPTURE_MAX_HEIGHT and not force_tiled:
            encoded = _capture_region(
                browser,
                x=0,
                y=0,
                width=width,
                height=total_height,
                output_format=output_format,
            )
            _validate_capture(encoded, width, total_height, output_format)
        else:
            encoded = _capture_tiled(
                browser,
                width,
                viewport_height,
                total_height,
                profile,
                fixed_elements,
                output_format,
                max_pixels,
                output_file,
            )
        destination.write_bytes(encoded)
    finally:
        # Cleanup is deliberately best-effort so it never replaces the capture
        # error that triggered it. The page may already be gone after a CDP fault.
        try:
            _scroll_to(browser, 0)
        except Exception:
            pass
        try:
            _restore_overlays(browser, hidden_registry)
        except Exception:
            pass
        if transparent_background:
            try:
                _restore_background(browser)
            except Exception:
                pass
        try:
            _send(browser, "Emulation.clearDeviceMetricsOverride")
        except Exception:
            pass
