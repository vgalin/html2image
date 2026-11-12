"""Shared, browser-agnostic primitives for full-page capture."""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple


DEFAULT_MAX_PIXELS = 100_000_000
VALID_FULL_PAGE_PROFILES = frozenset({"fast", "balanced", "robust"})
VALID_FIXED_ELEMENT_MODES = frozenset(
    {"auto", "preserve", "first", "last", "hide"}
)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


# A fixed or sticky element that is too small to be seen is ignored. Its
# content counts, since it can overflow an element that has no size itself.
_IS_OVERLAY_JS = r"""
const isOverlay = (element) => {
  const style = getComputedStyle(element);
  if (style.position !== 'fixed' && style.position !== 'sticky') return false;
  if (style.display === 'none' || style.visibility === 'hidden') return false;
  const rect = element.getBoundingClientRect();
  return Math.max(rect.width, element.scrollWidth) >= 4
    && Math.max(rect.height, element.scrollHeight) >= 4;
};
"""

OVERLAY_COUNT_JS = r"""
(() => {
  %s
  return [...document.querySelectorAll('*')].filter(isOverlay).length;
})()
""" % _IS_OVERLAY_JS

_SHOW_OVERLAYS_JS = r"""
(() => {
  %s
  const [key, mode, first, last] = %%s;
  const registry = window[key] || (window[key] = {entries: [], seen: new WeakSet()});
  const properties = ['opacity', 'transition', 'position', 'top', 'bottom'];

  // The page is scanned again for every tile: scrolling can load new elements
  // or make an existing one fixed.
  for (const element of document.querySelectorAll('*')) {
    if (registry.seen.has(element) || !isOverlay(element)) continue;
    registry.seen.add(element);
    const saved = {};
    for (const property of properties) {
      saved[property] = [
        element.style.getPropertyValue(property),
        element.style.getPropertyPriority(property)
      ];
    }
    const rect = element.getBoundingClientRect();
    const topDistance = Math.abs(rect.top);
    const bottomDistance = Math.abs(window.innerHeight - rect.bottom);
    const sticky = getComputedStyle(element).position === 'sticky';
    if (sticky && mode === 'auto') {
      // A sticky element stays where it is in the flow of the page.
      element.style.setProperty('position', 'relative', 'important');
      element.style.setProperty('top', 'auto', 'important');
      element.style.setProperty('bottom', 'auto', 'important');
    }
    registry.entries.push({
      element, saved, sticky, bottom: bottomDistance + 1 < topDistance
    });
  }

  for (const {element, saved, sticky, bottom} of registry.entries) {
    let visible;
    if (mode === 'hide') visible = false;
    else if (mode === 'first') visible = first;
    else if (mode === 'last') visible = last;
    else if (sticky) visible = true;
    else visible = bottom ? last : first;
    // Unlike `visibility`, `opacity` cannot be overridden by a descendant.
    for (const [property, value] of [['opacity', '0'], ['transition', 'none']]) {
      if (!visible) element.style.setProperty(property, value, 'important');
      else if (saved[property][0]) element.style.setProperty(property, ...saved[property]);
      else element.style.removeProperty(property);
    }
  }
})()
""" % _IS_OVERLAY_JS

_RESTORE_OVERLAYS_JS = r"""
(() => {
  const key = %s;
  for (const {element, saved} of (window[key] || {entries: []}).entries) {
    for (const [property, [value, priority]] of Object.entries(saved)) {
      if (value) element.style.setProperty(property, value, priority);
      else element.style.removeProperty(property);
    }
  }
  delete window[key];
})()
"""


def show_overlays_js(key: str, mode: str, first: bool, last: bool) -> str:
    """Return the script showing fixed and sticky elements as ``mode`` asks.

    ``first`` and ``last`` tell whether the tile about to be captured is the
    first or the last one. The elements found are remembered under
    ``window[key]`` until `restore_overlays_js` is run.
    """
    return _SHOW_OVERLAYS_JS % json.dumps([key, mode, first, last])


def restore_overlays_js(key: str) -> str:
    """Return the script undoing every change made by `show_overlays_js`."""
    return _RESTORE_OVERLAYS_JS % json.dumps(key)


class FullPageCaptureLimitError(RuntimeError):
    """Raised before a capture would exceed its configured resource budget."""


@dataclass(frozen=True)
class TileSegment:
    """One exact, non-overlapping portion of the final image."""

    capture_y: int
    capture_height: int
    paste_y: int
    content_height: int
    crop_top: int = 0


def output_format_from_filename(filename: str) -> str:
    """Return the encoder name for a supported output filename."""
    lowered = filename.lower()
    if lowered.endswith(".png"):
        return "png"
    if lowered.endswith((".jpg", ".jpeg")):
        return "jpeg"
    raise ValueError(
        "full_page output_file must end with .png, .jpg, or .jpeg "
        f"(got {filename!r})"
    )


def validate_viewport(width: int, height: int) -> Tuple[int, int]:
    """Validate and normalize the canonical layout viewport."""
    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, int)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
    ):
        raise ValueError(
            "full_page size must contain two strictly positive integers "
            f"(got {(width, height)!r})"
        )
    return width, height


def validate_full_page_profile(profile: object) -> str:
    if not isinstance(profile, str) or profile not in VALID_FULL_PAGE_PROFILES:
        choices = ", ".join(sorted(VALID_FULL_PAGE_PROFILES))
        raise ValueError(
            f"full_page_profile must be one of: {choices} (got {profile!r})"
        )
    return profile


def validate_fixed_element_mode(mode: object) -> str:
    if not isinstance(mode, str) or mode not in VALID_FIXED_ELEMENT_MODES:
        choices = ", ".join(sorted(VALID_FIXED_ELEMENT_MODES))
        raise ValueError(
            "full_page_fixed_elements must be one of: "
            f"{choices} (got {mode!r})"
        )
    return mode


def validate_max_pixels(max_pixels: Optional[int]) -> Optional[int]:
    """Validate the caller-controlled full-page resource budget."""
    if max_pixels is None:
        return None
    if (
        isinstance(max_pixels, bool)
        or not isinstance(max_pixels, int)
        or max_pixels <= 0
    ):
        raise ValueError(
            "full_page_max_pixels must be a strictly positive integer or None "
            f"(got {max_pixels!r})"
        )
    return max_pixels


def validate_stability_timeout(
    timeout: Optional[float],
) -> Optional[float]:
    """Validate a per-pass stability budget at every public boundary."""
    if timeout is None:
        return None
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError(
            "full_page_stability_timeout must be a strictly positive finite "
            f"float or None (got {timeout!r})"
        )
    return float(timeout)


def enforce_pixel_budget(
    width: int,
    height: int,
    max_pixels: Optional[int],
) -> int:
    """Reject an oversized final image instead of silently truncating it."""
    max_pixels = validate_max_pixels(max_pixels)
    pixel_count = int(width) * int(height)
    if max_pixels is not None and pixel_count > max_pixels:
        raise FullPageCaptureLimitError(
            "Full-page capture would contain "
            f"{pixel_count:,} pixels ({width}x{height}), exceeding "
            f"full_page_max_pixels={max_pixels:,}. Increase the limit or "
            "set it to None to disable this safety check."
        )
    return pixel_count


def next_tile_height(
    y: int,
    total_height: int,
    tile_height: int,
    viewport_height: int,
    fixed_elements: str,
) -> int:
    """Return the height of the tile starting at ``y``."""
    remaining = total_height - y
    if fixed_elements != "last":
        return min(tile_height, remaining)
    # The final tile is the whole last viewport, so that an element fixed at
    # its top is part of the image.
    if remaining <= viewport_height:
        return remaining
    return min(tile_height, remaining - viewport_height)


def validate_tile_plan(
    plan: Sequence[TileSegment],
    total_height: int,
) -> None:
    """Check ordering and exact coverage of the captured tiles."""
    if not plan:
        raise ValueError("tile plan must not be empty")

    expected_y = 0
    for segment in plan:
        if segment.capture_y < 0 or segment.paste_y < 0:
            raise ValueError("tile coordinates must not be negative")
        if segment.paste_y != expected_y:
            raise ValueError(
                f"tile plan has a gap or overlap at y={expected_y}"
            )
        if segment.content_height <= 0 or segment.capture_height <= 0:
            raise ValueError("tile dimensions must be positive")
        if segment.crop_top < 0:
            raise ValueError("tile crop_top must not be negative")
        if segment.crop_top + segment.content_height > segment.capture_height:
            raise ValueError("tile crop exceeds its declared capture height")
        expected_y += segment.content_height

    if expected_y != total_height:
        raise ValueError(
            f"tile plan covers {expected_y}px instead of {total_height}px"
        )


def image_dimensions(image_bytes: bytes) -> Tuple[int, int]:
    """Read PNG or JPEG dimensions without importing an imaging library."""
    if image_bytes.startswith(_PNG_SIGNATURE):
        if len(image_bytes) < 24 or image_bytes[12:16] != b"IHDR":
            raise ValueError("Invalid PNG image data")
        return struct.unpack(">II", image_bytes[16:24])

    if image_bytes[:2] == b"\xff\xd8":
        return _jpeg_dimensions(image_bytes)

    raise ValueError("Unsupported image data; expected PNG or JPEG")


def _jpeg_dimensions(image_bytes: bytes) -> Tuple[int, int]:
    offset = 2
    length = len(image_bytes)
    start_of_frame_markers = {
        0xC0, 0xC1, 0xC2, 0xC3,
        0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB,
        0xCD, 0xCE, 0xCF,
    }

    while offset < length:
        while offset < length and image_bytes[offset] != 0xFF:
            offset += 1
        while offset < length and image_bytes[offset] == 0xFF:
            offset += 1
        if offset >= length:
            break

        marker = image_bytes[offset]
        offset += 1
        if marker in (0x01, 0xD8, 0xD9):
            continue
        if offset + 2 > length:
            break

        segment_length = struct.unpack(">H", image_bytes[offset:offset + 2])[0]
        if segment_length < 2 or offset + segment_length > length:
            break
        if marker in start_of_frame_markers:
            if segment_length < 7:
                break
            height, width = struct.unpack(">HH", image_bytes[offset + 3:offset + 7])
            return width, height
        offset += segment_length

    raise ValueError("Invalid JPEG image data")


def import_pyvips_for_stitching():
    """Import the optional dependency only when tiling is actually required."""
    try:
        import pyvips  # type: ignore[import]
        return pyvips
    except ImportError:
        raise ImportError(
            "pyvips is required to assemble a tiled full-page capture. "
            'Install it with: pip install "html2image[full-page]"'
        ) from None


def _has_regular_tile_heights(tile_plan: Sequence[TileSegment]) -> bool:
    """Return whether vertical arrayjoin padding can only occur at the end."""
    if len(tile_plan) <= 1:
        return True
    regular_height = tile_plan[0].content_height
    return (
        all(
            segment.content_height == regular_height
            for segment in tile_plan[:-1]
        )
        and tile_plan[-1].content_height <= regular_height
    )


def stitch_tiles(
    tile_bytes: Sequence[bytes],
    tile_plan: Sequence[TileSegment],
    total_width: int,
    total_height: int,
    output_format: str,
) -> bytes:
    """Compose validated browser tiles with the current pyvips baseline."""
    if len(tile_bytes) != len(tile_plan):
        raise RuntimeError(
            f"Expected {len(tile_plan)} screenshot tiles, got {len(tile_bytes)}"
        )
    validate_tile_plan(tile_plan, total_height)

    pyvips = import_pyvips_for_stitching()
    preserve_alpha = output_format == "png"
    if not preserve_alpha and output_format != "jpeg":
        raise ValueError(f"Unsupported output format: {output_format!r}")

    normalized_tiles = []
    for index, (encoded_tile, segment) in enumerate(zip(tile_bytes, tile_plan)):
        tile = pyvips.Image.new_from_buffer(encoded_tile, "", access="sequential")
        required_height = segment.crop_top + segment.content_height
        if tile.width != total_width or tile.height < required_height:
            raise RuntimeError(
                f"Tile {index} has dimensions {tile.width}x{tile.height}; "
                f"expected width {total_width} and at least {required_height}px high"
            )

        tile = tile.crop(
            0,
            segment.crop_top,
            total_width,
            segment.content_height,
        )
        if preserve_alpha:
            if tile.bands == 3:
                tile = tile.bandjoin(255)
            elif tile.bands != 4:
                raise RuntimeError(
                    f"Tile {index} has unsupported band count {tile.bands}"
                )
        else:
            if tile.bands == 4:
                tile = tile.flatten(background=[255, 255, 255])
            if tile.bands != 3:
                raise RuntimeError(
                    f"Tile {index} has unsupported band count {tile.bands}"
                )

        normalized_tiles.append(tile)

    if _has_regular_tile_heights(tile_plan):
        # arrayjoin uses uniform cells. The invariant above guarantees that its
        # only padding is after the final short tile, where an exact crop is safe.
        canvas = pyvips.Image.arrayjoin(normalized_tiles, across=1)
        canvas = canvas.crop(0, 0, total_width, total_height)
    else:
        # Bottom-aligned overlay plans can contain a short tile before the last
        # full viewport. arrayjoin would insert padding in the middle and corrupt
        # geometry, so retain exact positioned insertion for those rare plans.
        if preserve_alpha:
            canvas = pyvips.Image.black(total_width, total_height, bands=4)
        else:
            canvas = pyvips.Image.black(total_width, total_height, bands=3) + 255
        for tile, segment in zip(normalized_tiles, tile_plan):
            canvas = canvas.insert(tile, 0, segment.paste_y)

    if output_format == "png":
        encoded = canvas.write_to_buffer(".png[compression=6]")
    else:
        encoded = canvas.write_to_buffer(".jpg[Q=90]")

    actual_width, actual_height = image_dimensions(encoded)
    if (actual_width, actual_height) != (total_width, total_height):
        raise RuntimeError(
            "Stitched image has unexpected dimensions "
            f"{actual_width}x{actual_height}; expected {total_width}x{total_height}"
        )
    return encoded
