"""Tests of the `selector` parameter of `screenshot()`.

Tests that take screenshots skip automatically if the browser is not found
on the current machine. They only open local pages.
"""

from html2image import (
    Html2Image,
    CaptureTooLargeError,
    ElementNotFoundError,
)
from html2image.browsers import _selector, chrome_cdp, firefox_bidi
from PIL import Image

import os
import pytest

RED, GREEN, BLUE, WHITE = (255, 0, 0), (0, 128, 0), (0, 0, 255), (255, 255, 255)

PAGE_STYLE = "<style>html, body { margin: 0; background: white }</style>"


def _box(element_id="t", left=50, top=60, width=200, height=100, style=""):
    return (
        f'<div id="{element_id}" style="position: absolute; left: {left}px; '
        f'top: {top}px; width: {width}px; height: {height}px; '
        f'background: red; {style}"></div>'
    )


def _page(*content):
    return PAGE_STYLE + "".join(content)


def _colors(path):
    """Returns the size of an image and its colors, most used first."""
    img = Image.open(path).convert("RGB")
    return img.size, [color for _, color in sorted(img.getcolors(1 << 24), reverse=True)]


def _assert_filled(path, size, color=RED):
    assert _colors(path) == (size, [color])


# Element with a green band at the top and a blue band at the bottom, to
# check that none of it is cut or repeated.
BANDS = (
    '<div style="height: 10px; background: green"></div>'
    '<div style="position: absolute; bottom: 0; left: 0; right: 0; '
    'height: 10px; background: blue"></div>'
)


def _banded_box(element_id, width, height, left=50, top=100):
    return _box(element_id, left, top, width, height).replace(
        "></div>", f">{BANDS}</div>"
    )


def _assert_banded(path, size):
    img = Image.open(path).convert("RGB")
    width, height = size
    assert img.size == size
    assert img.getpixel((width // 2, 2)) == GREEN
    assert img.getpixel((width // 2, height // 2)) == RED
    assert img.getpixel((width // 2, height - 3)) == BLUE


# Without a browser.

@pytest.mark.parametrize("box, padding, expected", [
    # Fractional coordinates are rounded outwards.
    ((10.5, 20.5, 100.4, 50.2), 0, (10, 20, 101, 51)),
    ((50, 60, 200, 100), 0, (50, 60, 200, 100)),
    ((50, 60, 200, 100), 20, (30, 40, 240, 140)),
    # The padding stops at the edges of the page.
    ((0, 0, 200, 100), 20, (0, 0, 220, 120)),
    ((700, 800, 200, 100), 20, (680, 780, 220, 120)),
    # So does an element partly outside of the page.
    ((-50, 60, 200, 100), 0, (0, 60, 150, 100)),
])
def test_element_clip(box, padding, expected):
    x, y, width, height = box
    measured = {
        "x": x, "y": y, "width": width, "height": height,
        "pageWidth": 900, "pageHeight": 900,
    }

    clip = _selector.element_clip(measured, padding)

    assert clip == dict(zip(("x", "y", "width", "height"), expected))


@pytest.mark.parametrize("box", [
    None,  # no matching element
    (50, 60, 0, 100),  # display: none, or no width
    (50, 60, 200, 0),
    (-300, 60, 200, 100),  # outside of the page
    (50, 1000, 200, 100),
])
def test_element_clip_nothing_to_capture(box):
    if box is not None:
        x, y, width, height = box
        box = {
            "x": x, "y": y, "width": width, "height": height,
            "pageWidth": 900, "pageHeight": 900,
        }

    assert _selector.element_clip(box, padding=10) is None


@pytest.mark.parametrize("clip_y, scroll_y, expected", [
    (100, 0, 0),  # already in the viewport
    (3000, 0, 2500),  # below: shown at the bottom of the viewport
    (100, 500, 100),  # above: shown at the top of the viewport
])
def test_viewport_scroll(clip_y, scroll_y, expected):
    box = {
        "scrollX": 0, "scrollY": scroll_y,
        "viewportWidth": 800, "viewportHeight": 600,
    }
    clip = {"x": 50, "y": clip_y, "width": 200, "height": 100}

    assert _selector.viewport_scroll(box, clip) == (0, expected)


def test_viewport_scroll_clip_larger_than_viewport():
    box = {
        "scrollX": 0, "scrollY": 0,
        "viewportWidth": 800, "viewportHeight": 600,
    }
    clip = {"x": 50, "y": 100, "width": 200, "height": 601}

    assert _selector.viewport_scroll(box, clip) is None


@pytest.fixture
def fake_hti(monkeypatch, tmp_path):
    """Html2Image with a fake Chrome, which records the pages it loads.

    The elements whose selector starts with "#missing" or "#large" are
    reported as missing or too large.
    """
    monkeypatch.setattr(chrome_cdp, "find_chrome", lambda executable: "chrome")
    hti = Html2Image(output_path=str(tmp_path), temp_path=str(tmp_path / "temp"))
    hti.loaded_pages = []

    def screenshot(input, output_path, output_file="screenshot.png",
                   size=(1920, 1080), elements=None, selector_padding=0):
        hti.loaded_pages.append({"size": size, "elements": elements})
        if elements is None:
            return None
        return (
            [e for e in elements if e[0].startswith("#missing")],
            [e for e in elements if e[0].startswith("#large")],
        )

    monkeypatch.setattr(hti.browser, "screenshot", screenshot)
    return hti


def test_selector_names_pages_then_selectors(fake_hti):
    paths = fake_hti.screenshot(
        html_str=["one", "two"],
        selector=["#a", "#b"],
        save_as="shot.png",
        size=[(800, 600), (400, 300)],
    )

    assert fake_hti.loaded_pages == [
        {"size": (800, 600), "elements": [("#a", "shot_0.png"), ("#b", "shot_1.png")]},
        {"size": (400, 300), "elements": [("#a", "shot_2.png"), ("#b", "shot_3.png")]},
    ]
    assert [os.path.basename(path) for path in paths] == [
        "shot_0.png", "shot_1.png", "shot_2.png", "shot_3.png",
    ]


def test_selector_string_gives_one_image_per_page(fake_hti):
    paths = fake_hti.screenshot(
        html_str="one", url="http://127.0.0.1:1/", selector="#a",
        save_as=["a.png", "b.png"],
    )

    assert [page["elements"] for page in fake_hti.loaded_pages] == [
        [("#a", "a.png")], [("#a", "b.png")],
    ]
    assert [os.path.basename(path) for path in paths] == ["a.png", "b.png"]


@pytest.mark.parametrize("selector", [None, "", []])
def test_empty_selector_captures_the_window(fake_hti, selector):
    paths = fake_hti.screenshot(html_str="one", selector=selector, save_as="a.png")

    assert fake_hti.loaded_pages == [{"size": (1920, 1080), "elements": None}]
    assert [os.path.basename(path) for path in paths] == ["a.png"]


def test_missing_elements_raise_after_the_other_images(fake_hti, tmp_path):
    with pytest.raises(ElementNotFoundError) as excinfo:
        fake_hti.screenshot(
            html_str=["one", "two"],
            selector=["#a", "#missing"],
            save_as="shot.png",
        )

    error = excinfo.value
    assert len(fake_hti.loaded_pages) == 2
    assert error.paths == [
        str(tmp_path / "shot_0.png"), str(tmp_path / "shot_2.png"),
    ]
    assert error.missing == [("#missing", "shot_1.png"), ("#missing", "shot_3.png")]
    assert '"#missing" (shot_1.png), "#missing" (shot_3.png)' in str(error)


def test_skip_missing_returns_the_saved_images(fake_hti, tmp_path):
    paths = fake_hti.screenshot(
        html_str=["one", "two"],
        selector=["#missing", "#a"],
        save_as="shot.png",
        skip_missing=True,
    )

    assert paths == [str(tmp_path / "shot_1.png"), str(tmp_path / "shot_3.png")]


@pytest.mark.parametrize("skip_missing", [False, True])
def test_too_large_is_raised_even_with_skip_missing(fake_hti, tmp_path, skip_missing):
    with pytest.raises(CaptureTooLargeError) as excinfo:
        fake_hti.screenshot(
            html_str="one",
            selector=["#a", "#large", "#missing"],
            save_as="shot.png",
            skip_missing=skip_missing,
        )

    error = excinfo.value
    assert error.paths == [str(tmp_path / "shot_0.png")]
    assert error.too_large == [("#large", "shot_1.png")]
    assert '"#large" (shot_1.png)' in str(error)
    assert f"at most {chrome_cdp.MAX_CAPTURE_SIZE} pixels" in str(error)
    assert f"Firefox at most {firefox_bidi.MAX_CAPTURE_SIZE}." in str(error)


@pytest.mark.parametrize("padding", [-1, -0.5])
def test_negative_selector_padding(fake_hti, padding):
    with pytest.raises(ValueError, match="selector_padding"):
        fake_hti.screenshot(html_str="one", selector="#a", selector_padding=padding)

    assert fake_hti.loaded_pages == []


@pytest.mark.parametrize(
    "browser", ["chrome-headless", "edge-headless", "firefox-headless"]
)
def test_selector_rejects_cli_backends(tmp_path, browser):
    try:
        hti = Html2Image(browser=browser, output_path=str(tmp_path), disable_logging=True)
    except FileNotFoundError:
        pytest.skip(f"'{browser}' executable not found on this machine")

    with pytest.raises(ValueError, match="selector"):
        hti.screenshot(html_str="Hello", selector="#a", save_as="cli.png")

    assert not (tmp_path / "cli.png").exists()


# With a browser.

BROWSERS = ["chrome", "firefox"]

# Edge runs the code of Chrome: it is only tried with two of the tests.
WITH_EDGE = pytest.mark.parametrize(
    "hti", ["chrome", "edge", "firefox"], indirect=True
)


@pytest.fixture(params=BROWSERS)
def hti(request, tmp_path):
    browser = request.param
    try:
        return Html2Image(
            browser=browser,
            output_path=str(tmp_path / "output"),
            temp_path=str(tmp_path / "temp"),
            size=(800, 600),
            disable_logging=True,
        )
    except FileNotFoundError:
        pytest.skip(f"'{browser}' executable not found on this machine")


@pytest.mark.parametrize("top", [
    60,  # in the window
    3000,  # far below the window
])
def test_selector_element(hti, top):
    [path] = hti.screenshot(html_str=_page(_box(top=top)), selector="#t")

    _assert_filled(path, (200, 100))


def test_selector_element_taller_than_window(hti):
    [path] = hti.screenshot(
        html_str=_page(_banded_box("t", 300, 2500)), selector="#t"
    )

    _assert_banded(path, (300, 2500))


# The container has no scrollbar: Firefox on Windows may draw a fading one,
# which would make two images of the same container differ.
SCROLL_CONTAINER = (
    '<div id="box" style="position: absolute; left: 20px; top: {top}px; '
    'width: 300px; height: 200px; overflow: auto; scrollbar-width: none; '
    'background: gray">'
    '<div style="height: 800px"></div>'
    '<div id="t" style="width: 200px; height: 100px; background: red"></div>'
    '<div style="height: 800px"></div>'
    '<div id="u" style="width: 200px; height: 100px; background: blue"></div>'
    '<div style="height: 800px"></div>'
    "</div>"
)


@pytest.mark.parametrize("top", [20, 2000])
def test_selector_element_in_scroll_container(hti, top):
    [path] = hti.screenshot(
        html_str=_page(SCROLL_CONTAINER.format(top=top)), selector="#t"
    )

    _assert_filled(path, (200, 100))


def test_selector_elements_in_same_scroll_container(hti):
    # Showing the first element scrolls the container, which moves the
    # second one: it is only measured right before its capture.
    first, second = hti.screenshot(
        html_str=_page(SCROLL_CONTAINER.format(top=20)),
        selector=["#t", "#u"],
    )

    _assert_filled(first, (200, 100))
    _assert_filled(second, (200, 100), BLUE)


def test_selector_order_does_not_change_scroll_container(hti):
    # Showing "#t" scrolls the container, which is scrolled back before the
    # next capture: the container looks as loaded in every image.
    page = _page(SCROLL_CONTAINER.format(top=20))

    with hti:
        [alone] = hti.screenshot(html_str=page, selector="#box", save_as="alone.png")
        _, after = hti.screenshot(html_str=page, selector=["#t", "#box"], save_as="after.png")
        before, _ = hti.screenshot(html_str=page, selector=["#box", "#t"], save_as="before.png")

    size, colors = _colors(alone)
    assert size == (300, 200)
    assert colors[0] == (128, 128, 128)
    expected = Image.open(alone).convert("RGB").tobytes()
    for path in (after, before):
        assert Image.open(path).convert("RGB").tobytes() == expected


FIXED_HEADER = (
    '<header style="position: fixed; top: 0; left: 0; right: 0; '
    'height: 80px; background: black; z-index: 1"></header>'
)
LONG_PAGE = '<div style="height: 5000px"></div>'


@WITH_EDGE
def test_selector_fixed_header_is_not_drawn_over_element(hti):
    short, tall = hti.screenshot(
        html_str=_page(
            FIXED_HEADER,
            LONG_PAGE,
            _box(top=3000),
            _banded_box("tall", 300, 2500, left=400, top=1000),
        ),
        selector=["#t", "#tall"],
    )

    _assert_filled(short, (200, 100))
    _assert_banded(tall, (300, 2500))


def test_selector_in_window_does_not_resize_the_page(hti):
    # The page would invert its colors on the first resize event. With the
    # padding, the second element reaches the bottom of the window.
    page = _page(
        _box(),
        _box("u", top=490, style="background: blue"),
        "<script>addEventListener('resize', () =>"
        " document.body.style.filter = 'invert(1)')</script>",
    )

    red, blue = hti.screenshot(
        html_str=page, selector=["#t", "#u"], selector_padding=10
    )

    assert _colors(red) == ((220, 120), [RED, WHITE])
    assert _colors(blue) == ((220, 120), [BLUE, WHITE])


def test_selector_padding(hti):
    padded, at_edge = hti.screenshot(
        html_str=_page(
            _box(left=300, top=300, style="box-shadow: 0 0 0 20px blue"),
            _box("edge", left=0, top=0),
        ),
        selector=["#t", "#edge"],
        selector_padding=20,
    )

    img = Image.open(padded).convert("RGB")
    assert img.size == (240, 140)
    assert img.getpixel((2, 2)) == BLUE
    assert img.getpixel((120, 70)) == RED
    # The padding stops at the top and left edges of the page.
    size, colors = _colors(at_edge)
    assert size == (220, 120)
    assert colors[0] == RED


def test_selector_several_selectors_and_pages(hti):
    page = _page(_box("a"), _box("b", top=3000, width=300, style="background: blue"))

    paths = hti.screenshot(
        html_str=[page, page.replace("blue", "green")],
        selector=["#a", "#b"],
        save_as=["a.png", "b.jpg", "c.png", "d.png"],
        size=[(800, 600), (400, 300)],
    )

    assert [os.path.basename(path) for path in paths] == [
        "a.png", "b.jpg", "c.png", "d.png",
    ]
    _assert_filled(paths[0], (200, 100))
    with Image.open(paths[1]) as jpeg:
        assert jpeg.format == "JPEG"
        assert jpeg.size == (300, 100)
    _assert_filled(paths[2], (200, 100))
    _assert_filled(paths[3], (300, 100), GREEN)


def test_selector_missing_elements(hti):
    hidden = _box("hidden", style="display: none")
    outside = _box("outside", left=-500)

    with pytest.raises(ElementNotFoundError) as excinfo:
        hti.screenshot(
            html_str=[_page(_box(), hidden, outside), _page(_box(top=3000))],
            selector=["#t", "#nothing", "#hidden", "#outside"],
            save_as="missing.png",
        )

    error = excinfo.value
    assert [os.path.basename(path) for path in error.paths] == [
        "missing_0.png", "missing_4.png",
    ]
    for path in error.paths:
        _assert_filled(path, (200, 100))
    assert error.missing == [
        ("#nothing", "missing_1.png"),
        ("#hidden", "missing_2.png"),
        ("#outside", "missing_3.png"),
        ("#nothing", "missing_5.png"),
        ("#hidden", "missing_6.png"),
        ("#outside", "missing_7.png"),
    ]
    assert sorted(os.listdir(hti.output_path)) == ["missing_0.png", "missing_4.png"]


@pytest.mark.parametrize("selector", ["div[", ""])
def test_selector_invalid_writes_nothing(hti, selector):
    with pytest.raises(ValueError, match="not a valid CSS selector"):
        hti.screenshot(
            html_str=[_page(_box()), _page(_box())],
            selector=["#t", selector],
        )

    assert os.listdir(hti.output_path) == []


def test_selector_does_not_restart_browser(hti):
    with hti:
        websocket = hti.browser._ws
        with pytest.raises(ElementNotFoundError):
            hti.screenshot(html_str=_page(_box()), selector="#nothing")

        assert hti.browser._ws is websocket


def test_selector_then_normal_screenshot_in_same_session(hti):
    page = _page(FIXED_HEADER, LONG_PAGE, _box(top=3000, height=2000))

    with hti:
        hti.screenshot(html_str=page, selector="#t", save_as="cropped.png")
        [path] = hti.screenshot(html_str=page, save_as="normal.png")

    img = Image.open(path).convert("RGB")
    assert img.size == (800, 600)
    assert img.getpixel((10, 10)) == (0, 0, 0)
    assert img.getpixel((10, 200)) == WHITE


@pytest.mark.parametrize("browser", BROWSERS)
def test_selector_page_without_doctype(tmp_path, browser):
    try:
        hti = Html2Image(
            browser=browser,
            output_path=str(tmp_path / "output"),
            temp_path=str(tmp_path / "temp"),
            size=(800, 600),
            disable_logging=True,
            add_doctype=False,
        )
    except FileNotFoundError:
        pytest.skip(f"'{browser}' executable not found on this machine")
    # Without doctype, the root element is 0 pixels high here, as nothing
    # is in the flow of the page.
    page = _page(
        FIXED_HEADER,
        _box("below", top=3000, style="background: blue"),
        _box(top=100),
        _banded_box("tall", 300, 2500, left=400),
    )

    # Without doctype, Firefox captures the elements outside of the root
    # element from the viewport, which only works if they fit in it.
    if browser == "firefox":
        with pytest.raises(CaptureTooLargeError) as excinfo:
            hti.screenshot(
                html_str=page, selector=["#below", "#t", "#tall"],
                save_as="quirks.png",
            )
        paths = excinfo.value.paths
        assert excinfo.value.too_large == [("#tall", "quirks_2.png")]
    else:
        paths = hti.screenshot(
            html_str=page, selector=["#below", "#t", "#tall"],
            save_as="quirks.png",
        )
        _assert_banded(paths[2], (300, 2500))

    # Firefox scrolls the page as little as possible to show "#below", so
    # that it stays clear of the fixed header, then scrolls it back: "#t"
    # would be under the header otherwise.
    _assert_filled(paths[0], (200, 100), BLUE)
    _assert_filled(paths[1], (200, 100))


LATE_ELEMENT = (
    "<script>setTimeout(() => document.body.insertAdjacentHTML("
    f"'beforeend', '{_box(top=3000)}'), 1500)</script>"
)


@pytest.mark.parametrize("browser", ["chrome"])
def test_selector_element_added_after_load(tmp_path, browser):
    # With --virtual-time-budget, the page runs for 5 seconds of virtual
    # time, in much less real time, before the element is measured.
    for flags in ([], ["--virtual-time-budget=5000"]):
        try:
            hti = Html2Image(
                browser=browser,
                output_path=str(tmp_path),
                size=(800, 600),
                disable_logging=True,
                custom_flags=flags or None,
            )
        except FileNotFoundError:
            pytest.skip(f"'{browser}' executable not found on this machine")

        if not flags:
            with pytest.raises(ElementNotFoundError):
                hti.screenshot(html_str=_page(LATE_ELEMENT), selector="#t")
        else:
            [path] = hti.screenshot(html_str=_page(LATE_ELEMENT), selector="#t")
            _assert_filled(path, (200, 100))


@WITH_EDGE
def test_selector_size_limit(hti):
    # The largest element that the browser captures in one go is exact,
    # without missing or repeated rows. One more pixel is refused, even
    # with skip_missing, which only skips the missing elements.
    if isinstance(hti.browser, firefox_bidi.FirefoxBiDi):
        limit = firefox_bidi.MAX_CAPTURE_SIZE
    else:
        limit = chrome_cdp.MAX_CAPTURE_SIZE
    page = _page(
        _banded_box("t", 300, limit),
        _banded_box("over", 300, limit + 1, left=400),
    )

    with pytest.raises(CaptureTooLargeError) as excinfo:
        hti.screenshot(
            html_str=page, selector=["#t", "#over", "#nothing"],
            save_as="limit.png", skip_missing=True,
        )

    [path] = excinfo.value.paths
    _assert_banded(path, (300, limit))
    assert excinfo.value.too_large == [("#over", "limit_1.png")]
    assert os.listdir(hti.output_path) == ["limit_0.png"]
