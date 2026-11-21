import io
import sys
import warnings

import pytest
from PIL import Image

from html2image import (
    BrowserError,
    BrowserTimeoutError,
    CaptureTooLargeError,
    FullPageWarning,
    Html2ImageError,
)
from html2image.browsers import _page_fit_common as common
from html2image.browsers import _chromium_page_fit as chromium_page_fit
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
    with pytest.raises(ValueError, match="two positive integers"):
        common.validate_viewport(*size)


@pytest.mark.parametrize("value", [[], {}, None, "turbo"])
def test_profile_validation_always_raises_value_error(value):
    with pytest.raises(ValueError, match="full_page_profile"):
        common.validate_full_page_profile(value)


def test_pixel_budget_is_exact_and_can_be_disabled():
    common.enforce_pixel_budget(100, 50, 5_000)
    common.enforce_pixel_budget(100, 50, None)
    with pytest.raises(CaptureTooLargeError, match="5,100 pixels"):
        common.enforce_pixel_budget(102, 50, 5_000)


@pytest.mark.parametrize("value", [0, -1, 1.5, True, "1000"])
def test_pixel_budget_rejects_invalid_configuration(value):
    with pytest.raises(ValueError, match="full_page_max_pixels"):
        common.validate_max_pixels(value)


@pytest.mark.parametrize(
    "value", [0, -1, float("nan"), float("inf"), True, "2"]
)
def test_stability_timeout_rejects_invalid_configuration(value):
    with pytest.raises(ValueError, match="full_page_stability_timeout"):
        common.validate_stability_timeout(value)


def test_stability_timeout_accepts_none_and_positive_numbers():
    common.validate_stability_timeout(None)
    common.validate_stability_timeout(2)
    common.validate_stability_timeout(0.5)


def _tile_heights(total_height, whole_last):
    heights = []
    while sum(heights) < total_height:
        heights.append(
            common.next_tile_height(
                sum(heights), total_height, 720, 720, whole_last
            )
        )
    return heights


def test_tiles_cover_document_exactly_once():
    assert _tile_heights(1_501, False) == [720, 720, 61]


def test_last_tile_can_be_a_whole_viewport():
    assert _tile_heights(1_501, True) == [720, 61, 720]
    assert _tile_heights(500, True) == [500]


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


@pytest.mark.parametrize(("height", "expected"), [(19, True), (30, False)])
def test_firefox_capture_in_one_go_must_have_the_size_of_the_page(
    monkeypatch, height, expected
):
    jpeg = _encoded_image("JPEG", size=(37, 19))
    monkeypatch.setattr(firefox_page_fit, "_capture", lambda *args: jpeg)

    image = firefox_page_fit._try_document_capture(None, 37, height, "jpeg")

    assert (image == jpeg) is expected


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


@pytest.mark.parametrize("error", [
    BrowserTimeoutError("Timed out"),
    BrowserError("The connection to the browser was lost."),
])
def test_chromium_capture_in_one_go_does_not_hide_errors(
    monkeypatch, tmp_path, error
):
    def fail(*args, **kwargs):
        raise error

    def no_tiles(*args, **kwargs):
        raise AssertionError("no tile should be captured")

    for name, value in [
        ("_sleep_ms", lambda *args: None),
        ("_settled_document_height", lambda *args: 1000),
        ("_send", lambda *args, **kwargs: {}),
        ("_capture", fail),
        ("capture_tiles", no_tiles),
    ]:
        monkeypatch.setattr(chromium_page_fit, name, value)

    with pytest.raises(type(error)):
        chromium_page_fit.capture_full_page(
            FakeBrowser(), str(tmp_path), "page.png", 1280, 720,
            profile="fast",
        )


class FakeBrowser:
    """A browser that shows a page without fixed element, which scrolls in
    the window."""

    def _evaluate(self, expression):
        return None if expression == common._INNER_SCROLL_JS else 0

    def _set_viewport(self, width, height):
        pass


def _fake_firefox_page(monkeypatch, height):
    def no_tiles(*args, **kwargs):
        raise AssertionError("no tile should be captured")

    for name, value in [
        ("_sleep_ms", lambda *args: None),
        ("_read_document_height", lambda *args: height),
        ("capture_tiles", no_tiles),
    ]:
        monkeypatch.setattr(firefox_page_fit, name, value)


def test_firefox_capture_in_one_go_does_not_hide_errors(
    monkeypatch, tmp_path
):
    def fail(*args, **kwargs):
        raise BrowserTimeoutError("Timed out")

    _fake_firefox_page(monkeypatch, 1000)
    monkeypatch.setattr(firefox_page_fit, "_capture", fail)

    with pytest.raises(BrowserTimeoutError):
        firefox_page_fit.capture_full_page(
            FakeBrowser(), str(tmp_path), "page.png", 1280, 720,
            profile="fast",
        )


def test_firefox_does_not_capture_too_large_pages_in_one_go(
    monkeypatch, tmp_path
):
    def tiles(*args, **kwargs):
        return b"tiles", []

    def no_capture_in_one_go(*args, **kwargs):
        raise AssertionError("Firefox refuses to capture it in one go")

    _fake_firefox_page(monkeypatch, 70000)
    monkeypatch.setattr(
        firefox_page_fit, "_try_document_capture", no_capture_in_one_go
    )
    monkeypatch.setattr(firefox_page_fit, "capture_tiles", tiles)

    firefox_page_fit.capture_full_page(
        FakeBrowser(), str(tmp_path), "page.png", 1280, 720, profile="fast",
        max_pixels=None,
    )

    assert (tmp_path / "page.png").read_bytes() == b"tiles"


# How far the anchors of a seam moved, and how far the page moved
# according to them. The first ones are all those measured on recorded
# pages on Nov. 16, 2026.
@pytest.mark.parametrize(("shifts", "expected"), [
    # BBC and Le Monde: the header shrank once the page was scrolled.
    ([-16, -16, -16], -16),
    ([-15.9, -15.9, -15.9], -16),
    ([-76, -76, -76], -76),
    # Tailwind: an animated picture moved by itself.
    ([0, 0, 0, 0, 0.7], 0),
    ([0, 0, 0, 0, 0.8], 0),
    ([0, 0, 0, 0, 3], 0),
    ([0, 0, 0, 0, 3.3], 0),
    ([0, 0, 0, 0, -5.6], 0),
    # CSS-Tricks: two elements of the same column moved.
    ([0, 0, 0, 11.8, 11.8], None),
    ([0, 0, 0, 8.1, 8.1], None),
    # NPR: no element crossed the seam.
    ([], None),
    # The page is only moved if all the anchors agree: a single anchor
    # that did not move tells that a part of the page did not move.
    ([12, 12], 12),
    ([12, 12, 0], None),
    ([12, 12, 12, 0], None),
    ([12, 12, 12, 5], None),
    ([-16, -16, -16, -16, -10], None),
    # A single anchor that moved is ignored if the others did not.
    ([0, 0, 12], 0),
    # A single anchor cannot tell that the page moved.
    ([0], 0),
    ([-16], None),
    ([0, -16], None),
])
def test_page_shift(shifts, expected):
    assert common.page_shift(shifts) == expected


# A single anchor and the backup anchors found above it, outside of it.
@pytest.mark.parametrize(("shifts", "backups", "expected"), [
    # The blocks above the seam all moved with it.
    ([12], [12, 12], 12),
    ([-16], [-16.4], -16),
    # It grew by itself: the blocks above it did not move.
    ([12], [0, 0], None),
    # All the backup anchors must agree, even with one of them left out.
    ([12], [12, 12, 0], None),
    ([12], [], None),
    # Backup anchors only confirm a single anchor that moved.
    ([0], [5, 5], 0),
    ([12, 12, 0], [12, 12], None),
])
def test_page_shift_with_backups(shifts, backups, expected):
    assert common.page_shift(shifts, backups) == expected


def _is_from(script, template):
    before, after = template.split("%s")
    return script.startswith(before) and script.endswith(after)


class FakePage:
    """Answers the scripts of `SeamChecker`, with the given shifts of the
    anchors, one list per reading."""

    def __init__(self, *readings):
        self.readings = list(readings)
        self.marked = []
        self.slept = 0

    def evaluate(self, script):
        if _is_from(script, common._MARK_ANCHORS_JS):
            self.marked.append(script)
            return 3
        if _is_from(script, common._ANCHOR_SHIFTS_JS):
            return self.readings.pop(0)
        return [True, True]

    def sleep(self, milliseconds):
        self.slept += milliseconds


def _checker(page):
    seams = common.SeamChecker(page.evaluate, page.sleep)
    seams.mark(720)
    seams.next_tile(0)
    return seams


def test_seam_checker_does_not_check_the_first_tile():
    page = FakePage()
    seams = common.SeamChecker(page.evaluate, page.sleep)
    assert seams.shift() == 0
    assert not page.readings


def test_seam_checker_waits_until_the_page_stops_moving():
    page = FakePage([0, 0, 0], [-8, -8, -8], [-16, -16, -16], [-16, -16, -16])
    seams = _checker(page)

    assert seams.shift() == 0
    assert seams.shift() == -16
    assert page.slept == 2 * common.SeamChecker.poll_ms
    assert seams.problem is None


@pytest.mark.parametrize(("readings", "expected", "problem"), [
    # A single anchor, then its backup anchors, read twice as they moved.
    ([[12], [12, 12], [12], [12, 12]], 12, None),
    ([[12], [0, 0], [12], [0, 0]], 0, "uneven"),
    ([[12], [], [12], []], 0, "no anchor"),
    # Backup anchors are not read if the single anchor did not move.
    ([[0]], 0, None),
])
def test_seam_checker_reads_backup_anchors_of_a_single_anchor(
    readings, expected, problem
):
    page = FakePage(*readings)
    seams = _checker(page)

    assert seams.shift() == expected
    assert seams.problem == problem
    assert not page.readings


def test_seam_checker_gives_up_on_a_page_that_keeps_moving(monkeypatch):
    monkeypatch.setattr(common.SeamChecker, "settle_timeout", 0)
    page = FakePage([-8, -8, -8], [-16, -16, -16])
    seams = _checker(page)

    assert seams.shift() == 0
    assert seams.problem == "moving"


def test_seam_checker_tells_if_the_page_moved_during_a_capture():
    page = FakePage([-76, -76, -76], [0, 0, 3.3])
    seams = common.SeamChecker(page.evaluate, page.sleep)
    seams.mark(1440)
    assert seams.moved()
    assert not seams.moved()


def test_seam_checker_warns_once_per_kind_of_unchecked_seam():
    uneven = [0, 0, 0, 11.8, 11.8]
    # Anchors that moved are read once more, to wait until they stop.
    page = FakePage([], uneven, uneven, [])
    seams = _checker(page)
    for row in (720, 1440, 2160):
        seams.shift()
        seams.mark(row + 720)
        seams.next_tile(row)

    assert seams.messages("page.png") == [
        common._UNCHECKED_SEAMS["no anchor"] % ("page.png", "720 px, 2160 px"),
        common._UNCHECKED_SEAMS["uneven"] % ("page.png", "1440 px"),
    ]


@pytest.mark.parametrize("page_fit", [chromium_page_fit, firefox_page_fit])
def test_full_page_warns_once_the_image_is_saved(
    monkeypatch, tmp_path, page_fit
):
    def tiles(*args, **kwargs):
        return b"tiles", ["page.png: a seam could not be checked."]

    for name, value in [
        ("_sleep_ms", lambda *args: None),
        ("_settled_document_height", lambda *args: 70000),
        ("_read_document_height", lambda *args: 70000),
        ("_send", lambda *args, **kwargs: {}),
        ("capture_tiles", tiles),
    ]:
        monkeypatch.setattr(page_fit, name, value, raising=False)

    with warnings.catch_warnings():
        warnings.simplefilter("error", FullPageWarning)
        with pytest.raises(FullPageWarning):
            page_fit.capture_full_page(
                FakeBrowser(), str(tmp_path), "page.png", 1280, 720,
                profile="fast", max_pixels=None,
            )
    assert (tmp_path / "page.png").read_bytes() == b"tiles"

    # The warning is shown where html2image was called.
    with pytest.warns(FullPageWarning, match="could not be checked") as caught:
        page_fit.capture_full_page(
            FakeBrowser(), str(tmp_path), "page.png", 1280, 720,
            profile="fast", max_pixels=None,
        )
    assert caught[0].filename == __file__


def _capture_two_tiles(page):
    """Captures two tiles of 720 px, as `capture_tiles()` would, and
    returns the warnings."""
    seams = common.SeamChecker(page.evaluate, page.sleep)
    for row in (0, 720):
        seams.shift()
        seams.mark(row + 720)
        seams.moved()
        seams.next_tile(row)
    return seams.messages("page.png")


def test_seam_checker_warns_if_the_last_tile_moved_unevenly():
    # The first tile, the seam, the second tile.
    page = FakePage([0, 0, 0], [0, 0, 0], [0, 0, 12, 12])
    assert _capture_two_tiles(page) == [
        common._UNCHECKED_SEAMS["uneven"] % ("page.png", "720 px"),
    ]


def test_seam_checker_warns_if_a_tile_moved_unevenly():
    # The anchors of the seam moved back before it was checked.
    page = FakePage([0, 0, 12, 12], [0, 0, 0], [0, 0, 0])
    assert _capture_two_tiles(page) == [
        common._UNCHECKED_SEAMS["uneven"] % ("page.png", "720 px"),
    ]


def test_seam_checker_without_anchor_on_a_page_that_did_not_move():
    page = FakePage([], [])
    seams = _checker(page)

    assert seams.shift(still=lambda: True) == 0
    assert seams.problem is None
    assert seams.shift(still=lambda: False) == 0
    assert seams.problem == "no anchor"


@pytest.mark.parametrize("page_fit", [chromium_page_fit, firefox_page_fit])
def test_full_page_leaves_the_viewport_as_it_is(
    monkeypatch, tmp_path, page_fit
):
    calls = []
    browser = FakeBrowser()
    browser._set_viewport = lambda *args: calls.append("_set_viewport")
    for name, value in [
        ("_sleep_ms", lambda *args: None),
        ("_settled_document_height", lambda *args: 70000),
        ("_read_document_height", lambda *args: 70000),
        ("_send", lambda browser, method, **kwargs: calls.append(method)),
        ("capture_tiles", lambda *args: (b"tiles", [])),
    ]:
        monkeypatch.setattr(page_fit, name, value, raising=False)

    page_fit.capture_full_page(
        browser, str(tmp_path), "page.png", 1280, 720, profile="fast",
        max_pixels=None,
    )

    # The viewport was given its size before the page was loaded. Setting
    # it again, or removing it, would send the page a resize event.
    assert "_set_viewport" not in calls
    assert "Emulation.clearDeviceMetricsOverride" not in calls


def _never(*args, **kwargs):
    raise AssertionError("nothing should be captured")


@pytest.mark.parametrize("page_fit", [chromium_page_fit, firefox_page_fit])
def test_full_page_refuses_a_jpeg_image_too_high_before_capturing_it(
    monkeypatch, tmp_path, page_fit
):
    for name, value in [
        ("_sleep_ms", lambda *args: None),
        ("_settled_document_height", lambda *args: 66000),
        ("_send", lambda *args, **kwargs: {}),
        ("_capture", _never),
        ("capture_tiles", _never),
    ]:
        monkeypatch.setattr(page_fit, name, value, raising=False)

    with pytest.raises(CaptureTooLargeError, match="JPEG"):
        page_fit.capture_full_page(
            FakeBrowser(), str(tmp_path), "page.jpg", 400, 720,
            profile="fast", max_pixels=None,
        )


class FakeTiles:
    """A page that grows beyond what a JPEG image can hold."""

    name = "Fake"
    width = 400
    viewport_height = tile_height = 720
    capture = _never

    def evaluate(self, expression):
        return []

    def sleep(self, milliseconds):
        pass

    def scroll_to(self, y):
        pass

    def settle(self):
        pass

    def measure(self):
        return 66000


def test_tiles_need_pyvips_before_the_page_is_scrolled(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyvips", None)
    scrolled = []
    page = FakeTiles()
    page.scroll_to = scrolled.append
    with pytest.raises(ImportError, match="pyvips"):
        common.capture_tiles(page, "auto", "png", None, "page.png")
    assert scrolled == []


def test_tiles_refuse_a_jpeg_image_that_grew_too_high():
    pytest.importorskip("pyvips")
    with pytest.raises(CaptureTooLargeError, match="JPEG"):
        common.capture_tiles(FakeTiles(), "auto", "jpeg", None, "page.jpg")


class EndlessTiles(FakeTiles):
    """A page of 10 x 80 px that grows by 20 px each time it is measured,
    as an endless feed would, shown 20 px at a time."""

    width = 10
    viewport_height = tile_height = 20

    def __init__(self):
        self.height, self.scroll_y = 60, 0

    def measure(self):
        self.height += 20
        return self.height

    def scroll_to(self, y):
        self.scroll_y = y

    def viewport(self):
        return self.scroll_y, self.viewport_height

    def capture(self, top, height, scroll_y, visible):
        tile = io.BytesIO()
        Image.new("RGB", (self.width, height)).save(tile, "PNG")
        return tile.getvalue(), top, height, 0


def test_tiles_stop_following_a_page_that_keeps_growing():
    pytest.importorskip("pyvips")
    # Without the limit, the page would grow beyond the pixel budget.
    image, messages = common.capture_tiles(
        EndlessTiles(), "auto", "png", 10 * 2_000, "feed.png"
    )

    # The page was 80 px high when the tiles started.
    assert common.image_dimensions(image) == (10, 80 + 10 * 20)
    assert common._GREW_TOO_MUCH % ("feed.png", 280) in messages


class StuckTiles(EndlessTiles):
    """The same page, in a browser that stops answering once the first
    tile is captured."""

    def __init__(self):
        super().__init__()
        self.scripts = []

    def evaluate(self, expression):
        self.scripts.append(expression)
        return []

    def capture(self, top, height, scroll_y, visible):
        raise BrowserTimeoutError("the browser did not answer in time")


def _cleaned_up(scripts):
    return [
        script for script in scripts
        if _is_from(script, common._FORGET_ANCHORS_JS)
        or _is_from(script, common._RESTORE_OVERLAYS_JS)
    ]


def test_tiles_leave_a_browser_that_will_be_restarted_as_it_is():
    page = StuckTiles()
    with pytest.raises(BrowserTimeoutError):
        common.capture_tiles(page, "auto", "png", None, "page.png")

    # The browser will be restarted. After a delay passed, each cleanup
    # would wait as long.
    assert not _cleaned_up(page.scripts)


def test_tiles_put_the_page_back_after_an_error_about_the_page():
    pytest.importorskip("pyvips")
    page = StuckTiles()
    page.capture = EndlessTiles.capture.__get__(page)
    with pytest.raises(CaptureTooLargeError):
        common.capture_tiles(page, "auto", "png", 10 * 100, "page.png")

    assert len(_cleaned_up(page.scripts)) == 2


@pytest.mark.parametrize("page_fit", [chromium_page_fit, firefox_page_fit])
def test_full_page_leaves_a_browser_that_will_be_restarted_as_it_is(
    monkeypatch, tmp_path, page_fit
):
    calls = []

    class RecordingBrowser(FakeBrowser):
        def _evaluate(self, expression):
            calls.append(expression)
            return super()._evaluate(expression)

    def stuck(*args):
        calls.append("stuck")
        raise BrowserTimeoutError("the browser did not answer in time")

    for name, value in [
        ("_sleep_ms", lambda *args: None),
        ("_settled_document_height", lambda *args: 70000),
        ("_read_document_height", lambda *args: 70000),
        ("_send", lambda browser, method, **kwargs: calls.append(method)),
        ("_scroll_to", lambda *args: calls.append("_scroll_to")),
        ("capture_tiles", stuck),
    ]:
        monkeypatch.setattr(page_fit, name, value, raising=False)

    with pytest.raises(BrowserTimeoutError):
        page_fit.capture_full_page(
            RecordingBrowser(), str(tmp_path), "page.png", 1280, 720,
            profile="fast", max_pixels=None,
        )
    assert calls[-1] == "stuck"


@pytest.mark.parametrize("output_file", ["page.png", "page.jpg"])
@pytest.mark.parametrize(
    "fixed_elements", ["auto", "first", "last", "hide", "preserve"]
)
def test_chrome_full_page_waits_for_a_paint_after_the_background_is_reset(
    monkeypatch, tmp_path, output_file, fixed_elements
):
    calls = []
    for name, value in [
        ("_sleep_ms", lambda *args: None),
        ("_settled_document_height", lambda *args: 1000),
        ("_send", lambda browser, method, **kwargs: calls.append(
            (method, kwargs)
        )),
        ("_capture", lambda *args, **kwargs: b"image"),
        ("_wait_for_paint", lambda browser, timeout_ms=None: calls.append(
            ("paint", timeout_ms)
        )),
    ]:
        monkeypatch.setattr(chromium_page_fit, name, value)

    chromium_page_fit.capture_full_page(
        FakeBrowser(), str(tmp_path), output_file, 400, 600,
        profile="fast", fixed_elements=fixed_elements, max_pixels=None,
    )
    background = "Emulation.setDefaultBackgroundColorOverride"
    if output_file.endswith(".png"):
        # Without this wait, a JPEG taken just after a PNG was sometimes
        # black where the page has no background. The wait is bounded.
        assert calls[-2] == (background, {})
        assert calls[-1][0] == "paint" and calls[-1][1] is not None
    else:
        assert all(call[0] != background for call in calls)
        assert all(call[1] is None for call in calls if call[0] == "paint")


@pytest.mark.parametrize(("scroll_height", "expected"), [
    # The page scrolls in the window.
    (None, (5000, [])),
    # It scrolls inside its body, and the window only shows 600 px.
    (600, (600, [common._SCROLLED_INSIDE % "page.png"])),
    (300, (600, [common._SCROLLED_INSIDE % "page.png"])),
    # The window shows it all.
    (5000, (5000, [])),
    (4999, (5000, [])),
])
def test_window_height(scroll_height, expected):
    assert common.window_height(
        lambda script: scroll_height, 5000, 600, "page.png"
    ) == expected


def test_stitch_tiles_does_not_let_pyvips_errors_out():
    pytest.importorskip("pyvips")
    with pytest.raises(Html2ImageError, match="could not be joined"):
        common.stitch_tiles(
            [b"not an image"], [common.TileSegment(0, 10, 0, 10)], 10, 10,
            "png",
        )
