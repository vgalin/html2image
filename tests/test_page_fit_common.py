import io

import pytest
from PIL import Image

from html2image import CaptureTooLargeError
from html2image.browsers import _page_fit_common as common
from html2image.browsers import _firefox_page_fit as firefox_page_fit


def _encoded_image(image_format, size=(7, 5), mode="RGB", color=None):
    if color is None:
        color = (12, 34, 56, 128) if mode == "RGBA" else (12, 34, 56)
    image = Image.new(mode, size, color)
    output = io.BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


@pytest.mark.parametrize(
    ("filename", "expected"),
    [("capture.png", "png"), ("capture.jpg", "jpeg"), ("capture.JPEG", "jpeg")],
)
def test_output_format_from_filename(filename, expected):
    assert common.output_format_from_filename(filename) == expected


def test_output_format_rejects_unsupported_extension():
    with pytest.raises(ValueError, match="must end with"):
        common.output_format_from_filename("capture.webp")


@pytest.mark.parametrize("size", [(0, 10), (10, -1), (10.5, 10), (True, 10)])
def test_validate_viewport_rejects_invalid_size(size):
    with pytest.raises(ValueError, match="strictly positive integers"):
        common.validate_viewport(*size)


@pytest.mark.parametrize("value", [[], {}, None, "turbo"])
def test_profile_validation_always_raises_value_error(value):
    with pytest.raises(ValueError, match="full_page_profile"):
        common.validate_full_page_profile(value)


def test_pixel_budget_is_exact_and_can_be_disabled():
    assert common.enforce_pixel_budget(100, 50, 5_000) == 5_000
    assert common.enforce_pixel_budget(100, 50, None) == 5_000
    with pytest.raises(CaptureTooLargeError, match="5,100 pixels"):
        common.enforce_pixel_budget(102, 50, 5_000)


@pytest.mark.parametrize("value", [0, -1, 1.5, True, "1000"])
def test_pixel_budget_rejects_invalid_configuration(value):
    with pytest.raises(ValueError, match="full_page_max_pixels"):
        common.enforce_pixel_budget(100, 50, value)


@pytest.mark.parametrize(
    "value", [0, -1, float("nan"), float("inf"), True, "2"]
)
def test_stability_timeout_rejects_invalid_configuration(value):
    with pytest.raises(ValueError, match="full_page_stability_timeout"):
        common.validate_stability_timeout(value)


def test_stability_timeout_accepts_none_and_positive_numbers():
    assert common.validate_stability_timeout(None) is None
    assert common.validate_stability_timeout(2) == 2.0


def _tile_heights(total_height, fixed_elements):
    heights = []
    while sum(heights) < total_height:
        heights.append(
            common.next_tile_height(
                sum(heights), total_height, 720, 720, fixed_elements
            )
        )
    return heights


def test_tiles_cover_document_exactly_once():
    assert _tile_heights(1_501, "auto") == [720, 720, 61]


def test_last_tile_is_a_whole_viewport_when_fixed_elements_are_kept_last():
    assert _tile_heights(1_501, "last") == [720, 61, 720]
    assert _tile_heights(500, "last") == [500]


def test_tile_plan_validation_rejects_gap():
    plan = [
        common.TileSegment(0, 10, 0, 10),
        common.TileSegment(11, 10, 11, 10),
    ]
    with pytest.raises(ValueError, match="gap or overlap"):
        common.validate_tile_plan(plan, 20)


def test_tile_plan_validation_rejects_crop_beyond_capture():
    plan = [common.TileSegment(0, 5, 0, 5, crop_top=1)]
    with pytest.raises(ValueError, match="crop exceeds"):
        common.validate_tile_plan(plan, 5)


def test_arrayjoin_is_used_only_when_short_padding_is_at_the_end():
    regular = [
        common.TileSegment(0, 5, 0, 5),
        common.TileSegment(5, 5, 5, 5),
        common.TileSegment(10, 2, 10, 2),
    ]
    bottom_aligned = [
        common.TileSegment(0, 5, 0, 5),
        common.TileSegment(5, 2, 5, 2),
        common.TileSegment(7, 5, 7, 5),
    ]
    assert common._has_regular_tile_heights(regular)
    assert not common._has_regular_tile_heights(bottom_aligned)


@pytest.mark.parametrize("image_format", ["PNG", "JPEG"])
def test_image_dimensions_without_imaging_runtime(image_format):
    encoded = _encoded_image(image_format, size=(37, 19))
    assert common.image_dimensions(encoded) == (37, 19)


def test_firefox_document_capture_rejects_wrong_encoded_format(monkeypatch):
    png = _encoded_image("PNG", size=(37, 19))
    monkeypatch.setattr(
        firefox_page_fit,
        "_capture_screenshot_bytes",
        lambda *args, **kwargs: png,
    )

    encoded, diagnostic = firefox_page_fit._try_document_capture(
        object(),
        expected_width=37,
        expected_height=19,
        output_format="jpeg",
    )

    assert encoded is None
    assert "non-JPEG" in diagnostic


def test_stitch_tiles_validates_tile_count_before_importing_pyvips():
    plan = [common.TileSegment(0, 5, 0, 5), common.TileSegment(5, 5, 5, 5)]
    with pytest.raises(RuntimeError, match="Expected 2 screenshot tiles, got 1"):
        common.stitch_tiles([b"not-an-image"], plan, 10, 10, "png")


def test_stitch_tiles_preserves_png_alpha_and_dimensions():
    pytest.importorskip("pyvips")
    plan = [common.TileSegment(0, 5, 0, 5), common.TileSegment(5, 5, 5, 5)]
    top = _encoded_image("PNG", size=(7, 5), mode="RGBA", color=(255, 0, 0, 0))
    bottom = _encoded_image("PNG", size=(7, 5), mode="RGBA", color=(0, 0, 255, 128))

    encoded = common.stitch_tiles([top, bottom], plan, 7, 10, "png")

    with Image.open(io.BytesIO(encoded)) as image:
        assert image.size == (7, 10)
        assert image.mode == "RGBA"
        assert image.getpixel((0, 0))[3] == 0
        assert image.getpixel((0, 9))[3] == 128


def test_stitch_tiles_flattens_jpeg_to_white():
    pytest.importorskip("pyvips")
    plan = [common.TileSegment(0, 5, 0, 5)]
    transparent = _encoded_image(
        "PNG", size=(7, 5), mode="RGBA", color=(255, 0, 0, 0)
    )

    encoded = common.stitch_tiles([transparent], plan, 7, 5, "jpeg")

    with Image.open(io.BytesIO(encoded)) as image:
        assert image.size == (7, 5)
        assert image.mode == "RGB"
        red, green, blue = image.getpixel((0, 0))
        assert red > 245 and green > 245 and blue > 245


def test_stitch_tiles_preserves_irregular_bottom_aligned_geometry():
    pytest.importorskip("pyvips")
    plan = [
        common.TileSegment(0, 5, 0, 5),
        common.TileSegment(5, 2, 5, 2),
        common.TileSegment(7, 5, 7, 5),
    ]
    tiles = [
        _encoded_image("PNG", size=(7, 5), color=(255, 0, 0)),
        _encoded_image("PNG", size=(7, 2), color=(0, 255, 0)),
        _encoded_image("PNG", size=(7, 5), color=(0, 0, 255)),
    ]

    encoded = common.stitch_tiles(tiles, plan, 7, 12, "png")

    with Image.open(io.BytesIO(encoded)).convert("RGB") as image:
        assert image.getpixel((0, 4)) == (255, 0, 0)
        assert image.getpixel((0, 5)) == (0, 255, 0)
        assert image.getpixel((0, 6)) == (0, 255, 0)
        assert image.getpixel((0, 7)) == (0, 0, 255)
