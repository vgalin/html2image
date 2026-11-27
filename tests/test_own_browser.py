"""Screenshots taken outside of a `with` block, as most users take them:
html2image will start the browser and close it for them, once for all the
pages of a call.

The tests of the other files share a browser, see `shared_browser` in
conftest.py. These ones never do, so that this path is still tried with
each browser, on every system.
"""

from html2image import Html2Image, PageLoadError
from html2image.browsers.chrome_cdp import ChromeCDP
from pathlib import Path
from PIL import Image

import os
import pytest

RED, GREEN, BLUE = (255, 0, 0), (0, 255, 0), (0, 0, 255)

# What a page leaves in the browser, and a page that shows what it finds of
# it: a red band where it finds something, a green one where it does not.
STATES = ["cookie", "local storage", "session storage", "window name"]

LEAVE_STATE = (
    "<script>document.cookie = 'h2i=1';"
    " localStorage.setItem('h2i', '1');"
    " sessionStorage.setItem('h2i', '1'); window.name = 'h2i';</script>"
)

SHOW_STATE = (
    '<body style="margin:0">'
    + '<div style="height:20px"></div>' * len(STATES)
    + "<script>[document.cookie.includes('h2i=1'),"
    " localStorage.getItem('h2i') !== null,"
    " sessionStorage.getItem('h2i') !== null, window.name === 'h2i']"
    ".forEach((found, index) => { document.body.children[index]"
    ".style.background = found ? 'rgb(255,0,0)' : 'rgb(0,255,0)' })"
    "</script></body>"
)


def found_state(path):
    """Returns what the page of SHOW_STATE found, by name."""
    img = Image.open(path).convert("RGB")
    return {
        name: img.getpixel((10, 20 * index + 10)) == RED
        for index, name in enumerate(STATES)
    }


def count_starts(monkeypatch, hti):
    """Returns the list of the profile folders of the browsers that `hti`
    will start, filled as they start."""
    browser = hti.browser
    name = (
        "_start_chrome" if isinstance(browser, ChromeCDP) else "_start_firefox"
    )
    start = getattr(browser, name)
    profiles = []

    def counted():
        process = browser.proc
        start()
        if browser.proc is not process:
            profiles.append(
                getattr(browser, "_user_data_dir", None)
                or browser._profile_dir
            )

    monkeypatch.setattr(browser, name, counted)
    return profiles


def _make_hti(browser, output_path, **options):
    """Html2Image for `browser`, or a skipped test if it is not installed."""
    try:
        return Html2Image(
            browser=browser, output_path=output_path, disable_logging=True,
            **options,
        )
    except FileNotFoundError:
        pytest.skip(f"'{browser}' executable not found on this machine")


def _page_of_color(color):
    return '<body style="margin:0;background:rgb%s"></body>' % (color,)


# The names of the browsers do not depend on the case.
@pytest.mark.parametrize("browser", ["edGe", "cHrOme", "fIrEfOx"])
def test_screenshot_string(browser, output_path):
    hti = _make_hti(browser, output_path)

    html = "Hello"
    css = "body{background: blue; font-size: 50px;}"

    paths = hti.screenshot(
        html_str=html, css_str=css, save_as="blue_big_hello.png"
    )

    img = Image.open(paths[0])
    pixels = img.load()

    assert (1920, 1080) == img.size  # default size

    # check colors at top left corner
    assert pixels[0, 0][:3] == (0, 0, 255)


@pytest.mark.parametrize("browser", ["chrome"])
def test_screenshot_urls_with_sizes_and_names(output_path, serve, browser):
    hti = _make_hti(browser, output_path)
    colors = [RED, GREEN, BLUE]
    names = ["red.png", "green.png", "blue.png"]

    paths = hti.screenshot(
        url=[serve(_page_of_color(color)) for color in colors],
        save_as=names,
        size=[(100, 100), (100, 1000)],
    )

    # The last size is used for the pages after it.
    sizes = [(100, 100), (100, 1000), (100, 1000)]
    assert [os.path.basename(path) for path in paths] == names
    for path, size, color in zip(paths, sizes, colors):
        img = Image.open(path).convert("RGB")
        assert img.size == size
        assert img.getpixel((50, 50)) == color


@pytest.mark.parametrize("browser", ["chrome", "firefox"])
def test_selector(browser, output_path):
    hti = _make_hti(browser, output_path)

    # Far below the window. The second page will be captured in a private
    # context.
    paths = hti.screenshot(
        html_str=[(
            '<body style="margin:0"><div id="box" style="position:absolute;'
            ' left:50px; top:3000px; width:200px; height:100px;'
            ' background:rgb%s"></div>' % (color,)
        ) for color in (RED, GREEN)],
        save_as=["red.png", "green.png"],
        selector="#box",
        size=(800, 600),
    )

    for path, color in zip(paths, (RED, GREEN)):
        img = Image.open(path).convert("RGB")
        assert img.size == (200, 100)
        assert img.getcolors() == [(200 * 100, color)]


@pytest.mark.parametrize("browser", ["chrome", "firefox"])
def test_full_page_in_tiles(browser, output_path):
    pytest.importorskip("pyvips")
    hti = _make_hti(browser, output_path)
    colors = [RED, GREEN, BLUE] * 2
    bands = "".join(
        '<div style="height:500px; background:rgb%s"></div>' % (color,)
        for color in colors
    )

    # The fixed badge will have the page captured in tiles. The second page
    # will be captured in a private context.
    paths = hti.screenshot(
        html_str=[(
            '<!doctype html><body style="margin:0">%s<div style="position:'
            'fixed; bottom:0; right:0; width:20px; height:20px;'
            ' background:black"></div>' % bands
        )] * 2,
        save_as=["first.png", "second.png"],
        size=(400, 600),
        full_page=True,
    )

    for path in paths:
        img = Image.open(path).convert("RGB")
        assert img.size == (400, 3000)
        for index, color in enumerate(colors):
            assert img.getpixel((10, index * 500 + 250)) == color


@pytest.mark.parametrize("browser", ["chrome", "firefox"])
def test_pdf(browser, output_path):
    hti = _make_hti(browser, output_path)

    paths = hti.pdf(
        html_str=["<h1>Hello</h1>", "<h1>World</h1>"],
        save_as=["hello.pdf", "world.pdf"],
    )

    for path in paths:
        data = Path(path).read_bytes()
        assert data.startswith(b"%PDF-")
        assert data.rstrip().endswith(b"%%EOF")


@pytest.mark.parametrize("browser", ["chrome", "firefox", "edge"])
def test_list_starts_one_browser_with_separate_pages(
    browser, output_path, serve, monkeypatch
):
    hti = _make_hti(browser, output_path)
    profiles = count_starts(monkeypatch, hti)

    paths = hti.screenshot(
        url=[serve(LEAVE_STATE), serve(SHOW_STATE), serve(SHOW_STATE)],
        save_as=["leave.png", "show.png", "show_again.png"],
        size=(200, 100),
    )

    # The pages found nothing of the first one, as with a browser of their
    # own.
    for path in paths[1:]:
        assert found_state(path) == dict.fromkeys(STATES, False)
    assert len(profiles) == 1
    assert hti.browser._ws is None
    assert not os.path.exists(profiles[0])


@pytest.mark.parametrize("browser", ["chrome", "firefox", "edge"])
def test_page_that_cannot_be_loaded_stops_the_list(
    browser, output_path, serve, closed_port_url
):
    hti = _make_hti(browser, output_path)

    with pytest.raises(PageLoadError):
        hti.screenshot(
            url=[serve(_page_of_color(RED)), closed_port_url,
                 serve(_page_of_color(GREEN))],
            save_as=["first.png", "failed.png", "last.png"],
            size=(100, 100),
        )

    assert os.listdir(output_path) == ["first.png"]
    assert hti.browser._ws is None


@pytest.mark.parametrize("browser", ["chrome", "firefox", "edge"])
def test_page_that_acts_after_its_screenshot(browser, output_path):
    hti = _make_hti(browser, output_path)
    pages = [
        # Opens a window, and will show an alert 2 seconds after it loaded:
        # after its screenshot, even on a slow machine. An alert shown
        # before the end of the capture would block it.
        '<body style="margin:0;background:rgb%s"><script>onload = () => {'
        " window.open('about:blank', '_blank', 'width=200,height=200');"
        " setTimeout(() => alert('still there'), 2000) }</script>" % (RED,),
        # Takes 3 s to load, while the alert would show.
        '<body style="margin:0;background:rgb%s"><script>'
        "const end = Date.now() + 3000; while (Date.now() < end) {}"
        "</script>" % (GREEN,),
        _page_of_color(BLUE),
    ]

    paths = hti.screenshot(
        html_str=pages, save_as=["red.png", "green.png", "blue.png"],
        size=(100, 100),
    )

    for path, color in zip(paths, (RED, GREEN, BLUE)):
        assert Image.open(path).convert("RGB").getpixel((50, 50)) == color
