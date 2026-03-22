"""Integration tests for the new backends: EdgeCDP and FirefoxBiDi.

Each test skips automatically if the required browser executable is not found
on the current machine.
"""

from html2image import Html2Image
from PIL import Image

import os
import pytest

OUTPUT_PATH = "tests_output"
os.makedirs(OUTPUT_PATH, exist_ok=True)


def _make_hti(browser, **kwargs):
    """Instantiate Html2Image, skipping if the browser is not installed."""
    try:
        return Html2Image(
            browser=browser,
            output_path=OUTPUT_PATH,
            disable_logging=True,
            **kwargs,
        )
    except FileNotFoundError:
        pytest.skip(f"'{browser}' executable not found on this machine")


# ---------------------------------------------------------------------------
# Edge CDP
# ---------------------------------------------------------------------------

def test_edge_cdp_exact_size():
    hti = _make_hti("edge-cdp")
    paths = hti.screenshot(
        html_str='<body style="margin:0;background:green"></body>',
        save_as="edge_cdp_exact_size.png",
        size=(800, 480),
    )
    img = Image.open(paths[0])
    assert img.size == (800, 480)


def test_edge_cdp_jpeg_output():
    hti = _make_hti("edge-cdp")
    paths = hti.screenshot(
        html_str='<body style="margin:0;background:#00aa00"></body>',
        save_as="edge_cdp_jpeg.jpg",
        size=(640, 360),
    )
    img = Image.open(paths[0])
    assert img.size == (640, 360)
    assert img.format == "JPEG"


def test_edge_cdp_html_string():
    hti = _make_hti("edge-cdp")
    paths = hti.screenshot(
        html_str='<body style="margin:0;background:blue"></body>',
        save_as="edge_cdp_html_str.png",
        size=(320, 240),
    )
    img = Image.open(paths[0]).convert("RGB")
    assert img.size == (320, 240)
    assert img.getpixel((0, 0)) == (0, 0, 255)


def test_edge_cdp_svg_transparent_background():
    hti = _make_hti("edge-cdp")
    paths = hti.screenshot(
        other_file="./examples/star.svg",
        save_as="edge_cdp_svg_alpha.png",
        size=(500, 500),
    )
    img = Image.open(paths[0]).convert("RGBA")
    assert img.size == (500, 500)
    assert img.getpixel((0, 0))[3] == 0


def test_edge_cdp_context_manager_reuse():
    hti = _make_hti("edge-cdp")
    sizes = [(400, 300), (640, 480), (320, 240)]
    paths = []

    with hti:
        for i, size in enumerate(sizes):
            result = hti.screenshot(
                html_str='<body style="margin:0;background:red"></body>',
                save_as=f"edge_cdp_ctx_{i}.png",
                size=size,
            )
            paths.extend(result)

    assert len(paths) == 3
    for path, expected_size in zip(paths, sizes):
        img = Image.open(path)
        assert img.size == expected_size


def test_edge_cdp_url():
    hti = _make_hti("edge-cdp")
    paths = hti.screenshot(
        url="https://www.example.com",
        save_as="edge_cdp_url.png",
        size=(1024, 768),
    )
    img = Image.open(paths[0])
    assert img.size == (1024, 768)


# ---------------------------------------------------------------------------
# Firefox BiDi
# ---------------------------------------------------------------------------

def test_firefox_bidi_exact_size():
    hti = _make_hti("firefox-bidi")
    paths = hti.screenshot(
        html_str='<body style="margin:0;background:green"></body>',
        save_as="firefox_bidi_exact_size.png",
        size=(800, 480),
    )
    img = Image.open(paths[0])
    assert img.size == (800, 480)


def test_firefox_bidi_jpeg_output():
    hti = _make_hti("firefox-bidi")
    paths = hti.screenshot(
        html_str='<body style="margin:0;background:#00aa00"></body>',
        save_as="firefox_bidi_jpeg.jpg",
        size=(640, 360),
    )
    img = Image.open(paths[0])
    assert img.size == (640, 360)
    assert img.format == "JPEG"


def test_firefox_bidi_html_string():
    hti = _make_hti("firefox-bidi")
    paths = hti.screenshot(
        html_str='<body style="margin:0;background:blue"></body>',
        save_as="firefox_bidi_html_str.png",
        size=(320, 240),
    )
    img = Image.open(paths[0]).convert("RGB")
    assert img.size == (320, 240)
    assert img.getpixel((0, 0)) == (0, 0, 255)


def test_firefox_bidi_context_manager_reuse():
    hti = _make_hti("firefox-bidi")
    sizes = [(400, 300), (640, 480), (320, 240)]
    paths = []

    with hti:
        for i, size in enumerate(sizes):
            result = hti.screenshot(
                html_str='<body style="margin:0;background:red"></body>',
                save_as=f"firefox_bidi_ctx_{i}.png",
                size=size,
            )
            paths.extend(result)

    assert len(paths) == 3
    for path, expected_size in zip(paths, sizes):
        img = Image.open(path)
        assert img.size == expected_size


def test_firefox_bidi_url():
    hti = _make_hti("firefox-bidi")
    paths = hti.screenshot(
        url="https://www.example.com",
        save_as="firefox_bidi_url.png",
        size=(1024, 768),
    )
    img = Image.open(paths[0])
    assert img.size == (1024, 768)


def test_firefox_bidi_html_file():
    hti = _make_hti("firefox-bidi")
    paths = hti.screenshot(
        html_file="./examples/blue_page.html",
        css_file="./examples/blue_background.css",
        save_as="firefox_bidi_html_file.png",
        size=(800, 600),
    )
    img = Image.open(paths[0]).convert("RGB")
    assert img.size == (800, 600)
    assert img.getpixel((0, 0)) == (0, 0, 255)
