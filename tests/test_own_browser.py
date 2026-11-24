"""Screenshots taken outside of a `with` block, as most users take them:
html2image will start the browser and close it for them.

The tests of the other files share a browser, see `shared_browser` in
conftest.py. These ones never do, so that this path is still tried with
each browser, on every system.
"""

from html2image import Html2Image
from pathlib import Path
from PIL import Image

import os
import pytest

RED, GREEN, BLUE = (255, 0, 0), (0, 255, 0), (0, 0, 255)


def _make_hti(browser, output_path):
    """Html2Image for `browser`, or a skipped test if it is not installed."""
    try:
        return Html2Image(
            browser=browser, output_path=output_path, disable_logging=True
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

    # Far below the window.
    [path] = hti.screenshot(
        html_str=(
            '<body style="margin:0"><div id="box" style="position:absolute;'
            ' left:50px; top:3000px; width:200px; height:100px;'
            ' background:red"></div>'
        ),
        selector="#box",
        size=(800, 600),
    )

    img = Image.open(path).convert("RGB")
    assert img.size == (200, 100)
    assert img.getcolors() == [(200 * 100, RED)]


@pytest.mark.parametrize("browser", ["chrome", "firefox"])
def test_full_page_in_tiles(browser, output_path):
    pytest.importorskip("pyvips")
    hti = _make_hti(browser, output_path)
    colors = [RED, GREEN, BLUE] * 2
    bands = "".join(
        '<div style="height:500px; background:rgb%s"></div>' % (color,)
        for color in colors
    )

    # The fixed badge will have the page captured in tiles.
    [path] = hti.screenshot(
        html_str=(
            '<!doctype html><body style="margin:0">%s<div style="position:'
            'fixed; bottom:0; right:0; width:20px; height:20px;'
            ' background:black"></div>' % bands
        ),
        size=(400, 600),
        full_page=True,
    )

    img = Image.open(path).convert("RGB")
    assert img.size == (400, 3000)
    for index, color in enumerate(colors):
        assert img.getpixel((10, index * 500 + 250)) == color


@pytest.mark.parametrize("browser", ["chrome", "firefox"])
def test_pdf(browser, output_path):
    hti = _make_hti(browser, output_path)

    [path] = hti.pdf(html_str="<h1>Hello</h1>", save_as="hello.pdf")

    data = Path(path).read_bytes()
    assert data.startswith(b"%PDF-")
    assert data.rstrip().endswith(b"%%EOF")
