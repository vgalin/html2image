"""Chromium full-page capture using a stable, caller-defined viewport.

The layout viewport is never resized to the document. Short documents use one
native CDP capture; long documents are captured in bounded regions and stitched.
"""

from __future__ import annotations

import base64
import math
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ._page_fit_common import (
    DEFAULT_MAX_PIXELS,
    OVERLAY_COUNT_JS,
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
        raise RuntimeError("JavaScript evaluation failed during full-page capture")
    result = evaluation.get("result", {})
    return result.get("value")


def _send(browser: Any, method: str, timeout: int = 30, **params: Any) -> Dict[str, Any]:
    command_id = browser.cdp_send(method, **params)
    return browser._wait_for_result(command_id, timeout=timeout)


def _set_viewport(browser: Any, width: int, height: int) -> None:
    _send(
        browser,
        "Emulation.setDeviceMetricsOverride",
        width=width,
        height=height,
        deviceScaleFactor=1,
        mobile=False,
    )


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


def _navigate(browser: Any, url: str) -> None:
    navigation_id = browser.cdp_send("Page.navigate", url=url)
    result = browser._wait_for_navigation_complete(navigation_id, timeout=50)
    error_text = (result.get("result") or {}).get("errorText")
    if error_text:
        raise RuntimeError("Navigation failed: %s" % error_text)
    _sleep_ms(browser, 250)


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
) -> bytes:
    params: Dict[str, Any] = {
        "format": output_format,
        "fromSurface": True,
        "captureBeyondViewport": True,
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
        raise RuntimeError("No screenshot data returned by Chromium CDP")
    return base64.b64decode(encoded)


def _validate_capture(
    encoded: bytes,
    width: int,
    height: int,
    output_format: str,
) -> None:
    if output_format == "png" and not encoded.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("Chromium returned a non-PNG full-page capture")
    if output_format == "jpeg" and not encoded.startswith(b"\xff\xd8"):
        raise RuntimeError("Chromium returned a non-JPEG full-page capture")
    actual = image_dimensions(encoded)
    if actual != (width, height):
        raise RuntimeError(
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


def _capture_tiled(
    browser: Any,
    width: int,
    viewport_height: int,
    total_height: int,
    profile: str,
    fixed_elements: str,
    output_format: str,
    max_pixels: Optional[int],
) -> bytes:
    # Fail before capturing every tile when the optional stitcher is absent.
    import_pyvips_for_stitching()
    tile_height = _choose_tile_height(width, viewport_height)
    registry_key: Optional[str] = None
    if fixed_elements != "preserve":
        registry_key = _overlay_registry_key()

    plan: List[TileSegment] = []
    tiles: List[bytes] = []
    y = 0
    try:
        while y < total_height:
            _scroll_to(browser, y)
            _wait_for_paint(browser)
            if profile != "fast":
                _sleep_ms(browser, _TILE_SCROLL_SETTLE_MS)

            # Scrolling can change the height of a page (a header that
            # collapses, content loaded on demand). The tiles follow the page
            # as it is now, not as it was when first measured.
            total_height = _measure_once(browser, viewport_height)
            enforce_pixel_budget(width, total_height, max_pixels)
            if y >= total_height:
                break
            height = next_tile_height(
                y, total_height, tile_height, viewport_height, fixed_elements
            )

            if registry_key is not None:
                _show_overlays(
                    browser,
                    registry_key,
                    fixed_elements,
                    first=y == 0,
                    last=y + height == total_height,
                )
            tile = _capture_region(
                browser,
                x=0,
                y=y,
                width=width,
                height=height,
                output_format="png",
            )
            _validate_capture(tile, width, height, "png")
            tiles.append(tile)
            plan.append(TileSegment(y, height, y, height))
            y += height
    finally:
        try:
            _scroll_to(browser, 0)
        finally:
            _restore_overlays(browser, registry_key)

    return stitch_tiles(tiles, plan, width, y, output_format)


def capture_full_page(
    browser: Any,
    input_url: str,
    output_path: str,
    output_file: str,
    width: int,
    viewport_height: int,
    stability_timeout: Optional[float] = None,
    profile: str = "robust",
    fixed_elements: str = "auto",
    max_pixels: Optional[int] = DEFAULT_MAX_PIXELS,
) -> None:
    """Capture a whole document without changing its layout viewport.

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

    page_enabled = False
    transparent_background = False
    hidden_registry: Optional[str] = None
    try:
        _send(browser, "Page.enable")
        page_enabled = True
        # The end of a navigation is detected from the lifecycle events.
        _send(browser, "Page.setLifecycleEventsEnabled", enabled=True)
        _set_viewport(browser, width, viewport_height)
        _navigate(browser, input_url)

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

        native_error: Optional[Exception] = None
        native_bytes: Optional[bytes] = None
        force_tiled = (
            total_height > viewport_height
            and overlay_count > 0
            and fixed_elements in {"auto", "last"}
        )
        if total_height <= _NATIVE_CAPTURE_MAX_HEIGHT and not force_tiled:
            try:
                native_bytes = _capture_region(
                    browser,
                    x=0,
                    y=0,
                    width=width,
                    height=total_height,
                    output_format=output_format,
                )
                _validate_capture(
                    native_bytes,
                    width,
                    total_height,
                    output_format,
                )
            except Exception as error:
                native_error = error
                native_bytes = None
        if native_bytes is not None:
            destination.write_bytes(native_bytes)
            return

        try:
            encoded = _capture_tiled(
                browser,
                width,
                viewport_height,
                total_height,
                profile,
                fixed_elements,
                output_format,
                max_pixels,
            )
            destination.write_bytes(encoded)
        except Exception as tiled_error:
            if native_error is not None:
                raise RuntimeError(
                    "Chromium native full-page capture failed with "
                    "%s: %s; tiled capture then failed with %s: %s"
                    % (
                        type(native_error).__name__,
                        native_error,
                        type(tiled_error).__name__,
                        tiled_error,
                    )
                ) from tiled_error
            raise
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
        if page_enabled:
            try:
                _send(browser, "Page.disable")
            except Exception:
                pass
