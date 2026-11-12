"""Correctness-first Firefox BiDi implementation of full-page capture.

The caller-provided viewport is the canonical rendering environment: its width
defines both layout and output width, while its height influences layout and
lazy loading but never caps the final image height.  Firefox's native document
capture is preferred and tiling is only a validated fallback.
"""

from __future__ import annotations

import base64
import json
import math
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from ._page_fit_common import (
    DEFAULT_MAX_PIXELS,
    TileSegment,
    build_tile_plan,
    enforce_pixel_budget,
    image_dimensions,
    import_pyvips_for_stitching,
    output_format_from_filename,
    stitch_tiles,
    validate_fixed_element_mode,
    validate_full_page_profile,
    validate_max_pixels,
    validate_stability_timeout,
    validate_viewport,
)


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
_PRE_CAPTURE_SETTLE_MS = 150


_DOM_DIM_JS = r"""
(() => {
  const doc = document.documentElement;
  const body = document.body;
  const width = Math.max(
    doc ? doc.scrollWidth : 0,
    doc ? doc.offsetWidth : 0,
    doc ? doc.clientWidth : 0,
    body ? body.scrollWidth : 0,
    body ? body.offsetWidth : 0,
    body ? body.clientWidth : 0
  );
  const height = Math.max(
    doc ? doc.scrollHeight : 0,
    doc ? doc.offsetHeight : 0,
    doc ? doc.clientHeight : 0,
    body ? body.scrollHeight : 0,
    body ? body.offsetHeight : 0,
    body ? body.clientHeight : 0
  );
  return { width, height, innerWidth: window.innerWidth, innerHeight: window.innerHeight };
})()
""".strip()

_CONTENT_HEIGHT_JS = (
    "Math.max("
    "document.documentElement ? document.documentElement.scrollHeight : 0, "
    "document.body ? document.body.scrollHeight : 0)"
)
_SCROLL_HEIGHT_JS = (
    "Math.max(0, (document.scrollingElement || document.documentElement)."
    "scrollHeight - window.innerHeight)"
)
_SCROLL_Y_JS = (
    "Math.max(0, Math.round(window.scrollY || window.pageYOffset || 0))"
)

_FIXED_FEATURES_JS = r"""
(() => {
  const result = { fixed_visible: 0, sticky_visible: 0 };
  for (const el of document.querySelectorAll("*")) {
    const style = window.getComputedStyle(el);
    if (!style || style.display === "none" || style.visibility === "hidden") continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 4 || rect.height < 4) continue;
    if (style.position === "fixed") result.fixed_visible += 1;
    if (style.position === "sticky") result.sticky_visible += 1;
  }
  return result;
})()
""".strip()

# Overlay state lives only on window, not in user DOM attributes.  Inline
# visibility values and priorities are restored exactly after the capture.
_PREPARE_OVERLAYS_JS_TEMPLATE = r"""
(() => {
  const key = __H2I_OVERLAY_STATE_KEY__;
  const normalizeSticky = __H2I_NORMALIZE_STICKY__;
  if (window[key]) return window[key].counts;
  const entries = [];
  const counts = { top: 0, bottom: 0, ambiguous: 0 };
  for (const el of document.querySelectorAll("*")) {
    const style = window.getComputedStyle(el);
    if (!style || !["fixed", "sticky"].includes(style.position)) continue;
    if (style.display === "none" || style.visibility === "hidden") continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 4 || rect.height < 4) continue;
    const topDistance = Math.abs(rect.top);
    const bottomDistance = Math.abs(window.innerHeight - rect.bottom);
    let category = "ambiguous";
    if (topDistance + 1 < bottomDistance) category = "top";
    if (bottomDistance + 1 < topDistance) category = "bottom";
    entries.push({
      el,
      category,
      normalizedSticky: normalizeSticky && style.position === "sticky",
      visibility: el.style.getPropertyValue("visibility"),
      visibilityPriority: el.style.getPropertyPriority("visibility"),
      position: el.style.getPropertyValue("position"),
      positionPriority: el.style.getPropertyPriority("position"),
      top: el.style.getPropertyValue("top"),
      topPriority: el.style.getPropertyPriority("top"),
      bottom: el.style.getPropertyValue("bottom"),
      bottomPriority: el.style.getPropertyPriority("bottom")
    });
    counts[category] += 1;
  }
  for (const entry of entries) {
    if (!entry.normalizedSticky) continue;
    entry.el.style.setProperty("position", "relative", "important");
    entry.el.style.setProperty("top", "auto", "important");
    entry.el.style.setProperty("bottom", "auto", "important");
  }
  window[key] = { entries, counts };
  return counts;
})()
""".strip()

_RESTORE_OVERLAYS_JS_TEMPLATE = r"""
(() => {
  const key = __H2I_OVERLAY_STATE_KEY__;
  const state = window[key];
  if (!state) return 0;
  const restoreProperty = (entry, name, valueName, priorityName) => {
    if (entry[valueName]) {
      entry.el.style.setProperty(name, entry[valueName], entry[priorityName]);
    } else {
      entry.el.style.removeProperty(name);
    }
  };
  for (const entry of state.entries) {
    restoreProperty(entry, "visibility", "visibility", "visibilityPriority");
    restoreProperty(entry, "position", "position", "positionPriority");
    restoreProperty(entry, "top", "top", "topPriority");
    restoreProperty(entry, "bottom", "bottom", "bottomPriority");
  }
  const count = state.entries.length;
  delete window[key];
  return count;
})()
""".strip()


def _overlay_state_script(
    template: str,
    state_key: str,
    *,
    normalize_sticky: bool = False,
) -> str:
    script = template.replace(
        "__H2I_OVERLAY_STATE_KEY__",
        json.dumps(state_key),
    )
    return script.replace(
        "__H2I_NORMALIZE_STICKY__",
        "true" if normalize_sticky else "false",
    )


def _overlay_visibility_js(
    state_key: str,
    visible_categories: Sequence[str],
) -> str:
    categories = json.dumps(list(visible_categories))
    encoded_state_key = json.dumps(state_key)
    return rf"""
(() => {{
  const state = window[{encoded_state_key}];
  if (!state) return 0;
  const visible = new Set({categories});
  let hidden = 0;
  for (const entry of state.entries) {{
    if (entry.normalizedSticky || visible.has(entry.category)) {{
      if (entry.visibility) {{
        entry.el.style.setProperty(
          "visibility", entry.visibility, entry.visibilityPriority
        );
      }} else {{
        entry.el.style.removeProperty("visibility");
      }}
    }} else {{
      entry.el.style.setProperty("visibility", "hidden", "important");
      hidden += 1;
    }}
  }}
  return hidden;
}})()
""".strip()


def _decode_remote_value(remote_value: Any) -> Any:
    """Decode a BiDi typed remote value into ordinary Python values."""
    if not isinstance(remote_value, dict):
        return remote_value
    value_type = remote_value.get("type")
    if value_type in {"undefined", "null"}:
        return None
    if value_type in {"string", "number", "boolean", "bigint"}:
        return remote_value.get("value")
    if value_type == "array":
        values = remote_value.get("value")
        if isinstance(values, list):
            return [_decode_remote_value(item) for item in values]
        return values
    if value_type in {"object", "map"}:
        raw_value = remote_value.get("value")
        if isinstance(raw_value, dict):
            return {
                str(key): _decode_remote_value(value)
                for key, value in raw_value.items()
            }
        if isinstance(raw_value, list):
            decoded: Dict[str, Any] = {}
            for entry in raw_value:
                if isinstance(entry, list) and len(entry) == 2:
                    key, value = entry
                elif (
                    isinstance(entry, dict)
                    and "key" in entry
                    and "value" in entry
                ):
                    key, value = entry["key"], entry["value"]
                else:
                    continue
                decoded[str(_decode_remote_value(key))] = _decode_remote_value(value)
            return decoded
    return remote_value


def _evaluate(browser: Any, expression: str, await_promise: bool = True) -> Any:
    message_id = browser._bidi_send(
        "script.evaluate",
        expression=expression,
        target={"context": browser._context_id},
        awaitPromise=await_promise,
    )
    response = browser._bidi_expect_ok(message_id, timeout=30)
    outer_result = response.get("result", {})
    if "exceptionDetails" in outer_result:
        raise RuntimeError(
            f"BiDi evaluation exception: {outer_result['exceptionDetails']}"
        )
    remote_value = outer_result.get("result", outer_result)
    return _decode_remote_value(remote_value)


def _set_viewport(browser: Any, width: int, height: int) -> None:
    message_id = browser._bidi_send(
        "browsingContext.setViewport",
        context=browser._context_id,
        viewport={"width": int(width), "height": int(height)},
        devicePixelRatio=1,
    )
    browser._bidi_expect_ok(message_id, timeout=20)


def _navigate(browser: Any, url: str) -> None:
    message_id = browser._bidi_send(
        "browsingContext.navigate",
        context=browser._context_id,
        url=url,
        wait="complete",
    )
    browser._bidi_expect_ok(message_id, timeout=50)


def _capture_screenshot_bytes(
    browser: Any,
    *,
    origin: str,
    output_format: str = "png",
) -> bytes:
    media_type = "image/jpeg" if output_format == "jpeg" else "image/png"
    message_id = browser._bidi_send(
        "browsingContext.captureScreenshot",
        context=browser._context_id,
        origin=origin,
        format={"type": media_type},
    )
    response = browser._bidi_expect_ok(message_id, timeout=60)
    encoded = response.get("result", {}).get("data")
    if not encoded:
        raise RuntimeError(f"No screenshot data returned for origin={origin!r}.")
    return base64.b64decode(encoded)


def _scroll_to(browser: Any, y: int) -> int:
    _evaluate(
        browser,
        "window.scrollTo({left: 0, top: "
        f"{int(y)}, behavior: 'instant'}}); true",
        await_promise=False,
    )
    return int(_evaluate(browser, _SCROLL_Y_JS) or 0)


def _scroll_top(browser: Any) -> None:
    _scroll_to(browser, 0)


def _sleep_ms(milliseconds: int) -> None:
    time.sleep(milliseconds / 1000.0)


def _read_document_height(browser: Any, viewport_height: int) -> int:
    dims = _evaluate(browser, _DOM_DIM_JS) or {}
    return max(viewport_height, int(math.ceil(float(dims.get("height") or 0))))


def _measure_stable_document_height(
    browser: Any,
    *,
    width: int,
    viewport_height: int,
    max_pixels: Optional[int],
    deadline_s: float,
    settle_after_s: float,
    min_duration_s: float,
) -> int:
    """Return the largest observed height after a stable polling interval."""
    start = time.monotonic()
    deadline = start + max(0.0, deadline_s)
    best_height = viewport_height
    last_height: Optional[int] = None
    stable_ticks = 0

    while True:
        height = _read_document_height(browser, viewport_height)
        enforce_pixel_budget(width, height, max_pixels)
        best_height = max(best_height, height)
        if height == last_height:
            stable_ticks += 1
        else:
            stable_ticks = 0
        last_height = height

        elapsed = time.monotonic() - start
        if elapsed >= max(settle_after_s, min_duration_s) and stable_ticks >= 3:
            break
        if time.monotonic() >= deadline:
            break
        _sleep_ms(_STABILITY_POLL_MS)

    return best_height


def _lazy_growth_probe(
    browser: Any,
    width: int,
    viewport_height: int,
    max_pixels: Optional[int],
) -> float:
    before_height = int(_evaluate(browser, _CONTENT_HEIGHT_JS) or 0)
    max_scroll = int(_evaluate(browser, _SCROLL_HEIGHT_JS) or 0)
    if max_scroll < 160:
        return 0.0
    for ratio in (0.75, 0.97):
        _scroll_to(browser, int(max_scroll * ratio))
        _sleep_ms(220)
    after_height = int(_evaluate(browser, _CONTENT_HEIGHT_JS) or 0)
    enforce_pixel_budget(
        width,
        max(viewport_height, after_height),
        max_pixels,
    )
    _scroll_top(browser)
    _sleep_ms(80)
    return (after_height - before_height) / max(1.0, float(before_height))


def _standard_lazy_warmup(
    browser: Any,
    width: int,
    viewport_height: int,
    max_pixels: Optional[int],
) -> None:
    max_scroll = int(_evaluate(browser, _SCROLL_HEIGHT_JS) or 0)
    if max_scroll <= 0:
        return
    for step in range(1, _STANDARD_SCROLL_STEPS + 1):
        _scroll_to(browser, int(max_scroll * step / _STANDARD_SCROLL_STEPS))
        _sleep_ms(_STANDARD_SCROLL_WAIT_MS)
        height = int(_evaluate(browser, _CONTENT_HEIGHT_JS) or 0)
        enforce_pixel_budget(
            width,
            max(viewport_height, height),
            max_pixels,
        )
    _scroll_top(browser)
    _sleep_ms(80)


def _exhaust_lazy_warmup(
    browser: Any,
    viewport_height: int,
    width: int,
    max_pixels: Optional[int],
) -> None:
    max_scroll = int(_evaluate(browser, _SCROLL_HEIGHT_JS) or 0)
    if max_scroll <= 0:
        return
    best_height = int(_evaluate(browser, _CONTENT_HEIGHT_JS) or 0)
    enforce_pixel_budget(width, max(viewport_height, best_height), max_pixels)
    scanned_to = 0
    stable_hits = 0
    for _ in range(_EXHAUST_SCROLL_MAX_ROUNDS):
        before_scroll = int(_evaluate(browser, _SCROLL_HEIGHT_JS) or 0)
        start = max(0, scanned_to - viewport_height)
        step = max(1, int(viewport_height * 0.85))
        target = start
        while target < before_scroll:
            _scroll_to(browser, target)
            _sleep_ms(_EXHAUST_TRAVERSE_WAIT_MS)
            target += step
        _scroll_to(browser, before_scroll)
        _sleep_ms(_EXHAUST_SCROLL_WAIT_MS)
        scanned_to = before_scroll

        current_height = int(_evaluate(browser, _CONTENT_HEIGHT_JS) or 0)
        enforce_pixel_budget(
            width,
            max(viewport_height, current_height),
            max_pixels,
        )
        current_scroll = int(_evaluate(browser, _SCROLL_HEIGHT_JS) or 0)
        if current_height > best_height + 4 or current_scroll > before_scroll + 4:
            best_height = max(best_height, current_height)
            stable_hits = 0
        else:
            stable_hits += 1
            if stable_hits >= _EXHAUST_SCROLL_STABLE_ROUNDS:
                break
    _scroll_top(browser)
    _sleep_ms(120)


def _bottom_paint_warmup(browser: Any) -> None:
    max_scroll = int(_evaluate(browser, _SCROLL_HEIGHT_JS) or 0)
    if max_scroll <= 0:
        return
    for ratio in (0.33, 0.66, 0.9, 1.0):
        _scroll_to(browser, int(max_scroll * ratio))
        _sleep_ms(_BOTTOM_PAINT_WAIT_MS)
    _scroll_top(browser)
    _sleep_ms(90)


def _overlay_features(browser: Any) -> Tuple[int, int]:
    features = _evaluate(browser, _FIXED_FEATURES_JS) or {}
    return (
        int(features.get("fixed_visible") or 0),
        int(features.get("sticky_visible") or 0),
    )


def _prepare_overlays(
    browser: Any,
    state_key: str,
    *,
    normalize_sticky: bool = False,
) -> None:
    _evaluate(
        browser,
        _overlay_state_script(
            _PREPARE_OVERLAYS_JS_TEMPLATE,
            state_key,
            normalize_sticky=normalize_sticky,
        ),
    )


def _set_visible_overlay_categories(
    browser: Any,
    state_key: str,
    categories: Sequence[str],
) -> None:
    _evaluate(browser, _overlay_visibility_js(state_key, categories))


def _restore_overlays(browser: Any, state_key: str) -> None:
    _evaluate(
        browser,
        _overlay_state_script(_RESTORE_OVERLAYS_JS_TEMPLATE, state_key),
    )


def _visible_categories_for_tile(
    mode: str,
    index: int,
    tile_count: int,
) -> Tuple[str, ...]:
    if mode == "hide":
        return ()
    if mode == "first":
        return ("top", "bottom", "ambiguous") if index == 0 else ()
    if mode == "last":
        return (
            ("top", "bottom", "ambiguous")
            if index == tile_count - 1
            else ()
        )
    if mode == "auto":
        if tile_count == 1:
            return ("top", "bottom", "ambiguous")
        visible = []
        if index == 0:
            visible.extend(("top", "ambiguous"))
        if index == tile_count - 1:
            visible.append("bottom")
        return tuple(visible)
    return ("top", "bottom", "ambiguous")


def _try_document_capture(
    browser: Any,
    *,
    expected_width: int,
    expected_height: int,
    output_format: str,
) -> Tuple[Optional[bytes], str]:
    try:
        image_bytes = _capture_screenshot_bytes(
            browser,
            origin="document",
            output_format=output_format,
        )
    except Exception as exc:
        return None, f"native document capture raised {type(exc).__name__}: {exc}"

    try:
        actual_width, actual_height = image_dimensions(image_bytes)
    except ValueError as exc:
        return None, f"native document capture returned invalid image data: {exc}"

    if output_format == "png" and not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return None, "native document capture returned non-PNG data"
    if output_format == "jpeg" and not image_bytes.startswith(b"\xff\xd8"):
        return None, "native document capture returned non-JPEG data"

    height_delta = abs(actual_height - expected_height)
    if (
        actual_width != expected_width
        or height_delta > _DOCUMENT_DIMENSION_TOLERANCE_PX
    ):
        return None, (
            "native document capture dimensions were "
            f"{actual_width}x{actual_height}, expected "
            f"{expected_width}x{expected_height} "
            f"(height tolerance {_DOCUMENT_DIMENSION_TOLERANCE_PX}px)"
        )
    return image_bytes, ""


def _build_viewport_tile_plan(
    total_height: int,
    viewport_height: int,
) -> Sequence[TileSegment]:
    """Build exact coverage whose final capture starts at max scroll.

    Bottom-aligning the final viewport avoids cropping a fixed element at the
    top of that viewport. This is required by the explicit ``last`` policy.
    """
    base_plan = build_tile_plan(total_height, viewport_height)
    max_scroll = max(0, total_height - viewport_height)
    starts = [
        segment.capture_y
        for segment in base_plan
        if segment.capture_y < max_scroll
    ]
    if not starts or starts[-1] != max_scroll:
        starts.append(max_scroll)

    plan = []
    for index, start in enumerate(starts):
        next_start = starts[index + 1] if index + 1 < len(starts) else total_height
        content_height = next_start - start
        plan.append(
            TileSegment(
                capture_y=start,
                capture_height=viewport_height,
                paste_y=start,
                content_height=content_height,
            )
        )
    return plan


def _capture_tiled_viewport(
    browser: Any,
    *,
    width: int,
    total_height: int,
    viewport_height: int,
    output_format: str,
    fixed_elements: str,
    overlay_state_key: str,
) -> bytes:
    # Fail before capturing every tile when the optional stitcher is absent.
    import_pyvips_for_stitching()
    if fixed_elements == "last":
        base_plan = _build_viewport_tile_plan(total_height, viewport_height)
    else:
        base_plan = build_tile_plan(total_height, viewport_height)
    adjusted_plan = []
    tiles = []
    prepare_overlays = fixed_elements != "preserve"

    if prepare_overlays:
        _prepare_overlays(
            browser,
            overlay_state_key,
            normalize_sticky=fixed_elements == "auto",
        )
    try:
        for index, segment in enumerate(base_plan):
            if prepare_overlays:
                categories = _visible_categories_for_tile(
                    fixed_elements,
                    index,
                    len(base_plan),
                )
                _set_visible_overlay_categories(
                    browser,
                    overlay_state_key,
                    categories,
                )

            _scroll_to(browser, segment.capture_y)
            _sleep_ms(_TILE_SCROLL_WAIT_MS)
            actual_y = int(_evaluate(browser, _SCROLL_Y_JS) or 0)
            if (
                actual_y > segment.capture_y
                or (
                    fixed_elements == "last"
                    and actual_y != segment.capture_y
                )
            ):
                raise RuntimeError(
                    "Firefox did not reach the requested tile position: "
                    f"requested y={segment.capture_y}, actual y={actual_y}."
                )
            crop_top = segment.paste_y - actual_y
            tile = _capture_screenshot_bytes(browser, origin="viewport")
            tile_width, tile_height = image_dimensions(tile)
            if (tile_width, tile_height) != (width, viewport_height):
                raise RuntimeError(
                    f"Firefox viewport tile {index} has dimensions "
                    f"{tile_width}x{tile_height}; expected "
                    f"{width}x{viewport_height}."
                )
            if crop_top + segment.content_height > tile_height:
                raise RuntimeError(
                    f"Firefox tile {index} cannot cover its assigned page range."
                )
            adjusted_plan.append(
                TileSegment(
                    capture_y=actual_y,
                    capture_height=tile_height,
                    paste_y=segment.paste_y,
                    content_height=segment.content_height,
                    crop_top=crop_top,
                )
            )
            tiles.append(tile)

        final_height = _read_document_height(browser, viewport_height)
        if final_height > total_height + _DOCUMENT_DIMENSION_TOLERANCE_PX:
            raise RuntimeError(
                "The page grew during Firefox's tiled capture "
                f"({total_height}px to {final_height}px); refusing to return "
                "a silently truncated image."
            )
    finally:
        if prepare_overlays:
            _restore_overlays(browser, overlay_state_key)

    return stitch_tiles(
        tiles,
        adjusted_plan,
        width,
        total_height,
        output_format,
    )


def _validate_options(
    profile: str,
    fixed_elements: str,
) -> None:
    validate_full_page_profile(profile)
    validate_fixed_element_mode(fixed_elements)


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
    """Capture a complete Firefox page with a canonical layout viewport.

    ``width`` is both the CSS layout width and exact output width.
    ``viewport_height`` remains the rendering viewport height; the final image
    grows to the measured document height and is never silently clamped.
    """
    width, viewport_height = validate_viewport(width, viewport_height)
    _validate_options(profile, fixed_elements)
    stability_timeout = validate_stability_timeout(stability_timeout)
    max_pixels = validate_max_pixels(max_pixels)
    output_format = output_format_from_filename(output_file)
    destination = Path(output_path) / output_file
    document_diagnostic = "native document capture was not attempted"
    overlay_state_prepared = False
    overlay_state_key = f"__html2imagePageFit_{uuid.uuid4().hex}__"

    try:
        # The canonical viewport must be active before navigation because CSS,
        # script bootstrapping and lazy-load observers can all inspect it.
        _set_viewport(browser, width, viewport_height)
        _navigate(browser, input_url)
        _sleep_ms(250)

        if profile == "fast":
            total_height = _read_document_height(browser, viewport_height)
        else:
            total_height = _measure_stable_document_height(
                browser,
                width=width,
                viewport_height=viewport_height,
                max_pixels=max_pixels,
                deadline_s=(
                    stability_timeout
                    if stability_timeout is not None
                    else _STABILITY_DEADLINE_QUICK_S
                ),
                settle_after_s=_STABILITY_SETTLE_QUICK_S,
                min_duration_s=_STABILITY_MIN_QUICK_S,
            )
            growth = _lazy_growth_probe(
                browser,
                width,
                viewport_height,
                max_pixels,
            )
            if profile == "balanced":
                _standard_lazy_warmup(
                    browser,
                    width,
                    viewport_height,
                    max_pixels,
                )
                if growth >= _AUTO_PROBE_GROWTH_TRIGGER:
                    _standard_lazy_warmup(
                        browser,
                        width,
                        viewport_height,
                        max_pixels,
                    )
            elif profile == "robust":
                # Robust also handles lazy content with reserved geometry,
                # which a height-growth probe cannot detect.
                _exhaust_lazy_warmup(
                    browser,
                    viewport_height,
                    width,
                    max_pixels,
                )
                _bottom_paint_warmup(browser)

            if (
                profile == "robust"
                or growth >= _AUTO_PROBE_GROWTH_TRIGGER
            ):
                after_warmup_height = _measure_stable_document_height(
                    browser,
                    width=width,
                    viewport_height=viewport_height,
                    max_pixels=max_pixels,
                    deadline_s=(
                        stability_timeout
                        if stability_timeout is not None
                        else _DEADLINE_AFTER_WARMUP_S
                    ),
                    settle_after_s=_SETTLE_AFTER_WARMUP_S,
                    min_duration_s=_MIN_AFTER_WARMUP_S,
                )
                total_height = max(total_height, after_warmup_height)

        total_height = max(viewport_height, total_height)
        enforce_pixel_budget(width, total_height, max_pixels)
        _set_viewport(browser, width, viewport_height)
        _scroll_top(browser)
        _sleep_ms(_PRE_CAPTURE_SETTLE_MS)

        fixed_count, sticky_count = _overlay_features(browser)
        overlay_count = fixed_count + sticky_count
        force_tiling = (
            total_height > viewport_height
            and fixed_elements in {"auto", "last"}
            and overlay_count > 0
        )

        if not force_tiling:
            if fixed_elements == "hide" and overlay_count > 0:
                _prepare_overlays(browser, overlay_state_key)
                overlay_state_prepared = True
                _set_visible_overlay_categories(browser, overlay_state_key, ())
            image_bytes, document_diagnostic = _try_document_capture(
                browser,
                expected_width=width,
                expected_height=total_height,
                output_format=output_format,
            )
            if image_bytes is not None:
                destination.write_bytes(image_bytes)
                return
            if overlay_state_prepared:
                _restore_overlays(browser, overlay_state_key)
                overlay_state_prepared = False
        else:
            document_diagnostic = (
                "native document capture skipped because fixed_elements="
                f"{fixed_elements!r} requires explicit tile placement"
            )

        # The document may have changed while Firefox attempted the native
        # capture.  Re-measure once so the fallback cannot truncate that growth.
        fallback_height = _read_document_height(browser, viewport_height)
        total_height = max(total_height, fallback_height)
        enforce_pixel_budget(width, total_height, max_pixels)

        try:
            stitched = _capture_tiled_viewport(
                browser,
                width=width,
                total_height=total_height,
                viewport_height=viewport_height,
                output_format=output_format,
                fixed_elements=fixed_elements,
                overlay_state_key=overlay_state_key,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Firefox full-page capture failed. {document_diagnostic}. "
                f"The tiled fallback also failed: {exc}"
            ) from exc
        destination.write_bytes(stitched)
    finally:
        # Temporary overlay visibility and scrolling never leak into a browser
        # instance kept open by the caller, including on capture failures.
        try:
            _restore_overlays(browser, overlay_state_key)
        except Exception:
            pass
        try:
            _scroll_top(browser)
        except Exception:
            pass
        try:
            _set_viewport(browser, width, viewport_height)
        except Exception:
            pass
