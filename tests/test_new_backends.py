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


# ---------------------------------------------------------------------------
# full_page integration tests
# ---------------------------------------------------------------------------

# Short card fixture — body height is explicitly 800px.
# 800 > _PROBE_VIEWPORT_H (720) > user viewport (600), so full_page must capture
# 800px rather than the user viewport height (600px).
_SHORT_CARD_HTML = """\
<!DOCTYPE html>
<html>
<head><style>
  body { margin: 0; height: 800px; background: #e0e0ff; }
  .card { width: 300px; padding: 20px; background: white; border: 1px solid #aaa; }
</style></head>
<body><div class="card"><h1>Short card</h1><p>Content.</p></div></body>
</html>
"""

# Long article fixture — ~3000px tall with 30 paragraphs.
_LONG_ARTICLE_HTML = """\
<!DOCTYPE html>
<html>
<head><style>
  body {{ margin: 0; padding: 20px; background: #fff; font-family: sans-serif; }}
  p {{ height: 100px; margin: 0 0 10px; background: #f5f5f5; }}
</style></head>
<body><h1>Long article</h1>{paragraphs}</body>
</html>
""".format(paragraphs="\n".join(f"<p>Paragraph {i}</p>" for i in range(30)))


def test_chrome_cdp_full_page_short_card():
    """Chrome CDP full_page=True: height must exceed viewport when content is taller than it."""
    hti = _make_hti("chrome-cdp")
    viewport = (800, 600)
    paths = hti.screenshot(
        html_str=_SHORT_CARD_HTML,
        save_as="chrome_cdp_full_page_short.png",
        size=viewport,
        full_page=True,
    )
    img = Image.open(paths[0])
    # body height is 800px — full_page must capture 800px, not the user viewport (600px)
    assert img.width == viewport[0]
    assert img.height > viewport[1]   # 800 > 600 : captured beyond user viewport
    assert img.height < 1200          # not as tall as long article (~3000px)


def test_chrome_cdp_full_page_long_article():
    """Chrome CDP full_page=True: very tall page captured beyond viewport."""
    hti = _make_hti("chrome-cdp")
    viewport = (1280, 720)
    paths = hti.screenshot(
        html_str=_LONG_ARTICLE_HTML,
        save_as="chrome_cdp_full_page_long.png",
        size=viewport,
        full_page=True,
    )
    img = Image.open(paths[0])
    # 30 × (100px + 10px margin) + header ≈ 3300px — must exceed the viewport.
    assert img.width == viewport[0]
    assert img.height > viewport[1]


def test_chrome_cdp_full_page_false_unchanged():
    """full_page=False must produce an image exactly at the requested size."""
    hti = _make_hti("chrome-cdp")
    size = (800, 400)
    paths = hti.screenshot(
        html_str='<body style="margin:0;background:green"></body>',
        save_as="chrome_cdp_full_page_false.png",
        size=size,
        full_page=False,
    )
    img = Image.open(paths[0])
    assert img.size == size


def test_firefox_bidi_full_page_long_article():
    """Firefox BiDi full_page=True: very tall page captured beyond viewport."""
    hti = _make_hti("firefox-bidi")
    viewport = (1280, 720)
    paths = hti.screenshot(
        html_str=_LONG_ARTICLE_HTML,
        save_as="firefox_bidi_full_page_long.png",
        size=viewport,
        full_page=True,
    )
    img = Image.open(paths[0])
    assert img.width == viewport[0]
    assert img.height > viewport[1]


# ---------------------------------------------------------------------------
# full_page_profile integration tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("profile", ["robust", "balanced", "fast"])
def test_chrome_cdp_full_page_profiles_short_card(profile):
    """Tous les profils Chromium capturent correctement une page statique 800px."""
    hti = _make_hti("chrome-cdp")
    paths = hti.screenshot(
        html_str=_SHORT_CARD_HTML,
        save_as=f"chrome_cdp_full_page_{profile}_short.png",
        size=(800, 600),
        full_page=True,
        full_page_profile=profile,
    )
    img = Image.open(paths[0])
    assert img.width == 800
    assert img.height > 600    # body 800px > viewport 600px
    assert img.height < 1200   # pas parasite par la constante interne


@pytest.mark.parametrize("profile", ["robust", "balanced", "fast"])
def test_chrome_cdp_full_page_profiles_long_article(profile):
    """Tous les profils Chromium capturent une page longue au-delà du viewport."""
    hti = _make_hti("chrome-cdp")
    paths = hti.screenshot(
        html_str=_LONG_ARTICLE_HTML,
        save_as=f"chrome_cdp_full_page_{profile}_long.png",
        size=(1280, 720),
        full_page=True,
        full_page_profile=profile,
    )
    img = Image.open(paths[0])
    assert img.width == 1280
    assert img.height > 720


def test_chrome_cdp_full_page_robust_default_unchanged():
    """Non-regression Chrome : defaut sans parametre == robust explicite."""
    hti = _make_hti("chrome-cdp")
    p1 = hti.screenshot(
        html_str=_SHORT_CARD_HTML,
        save_as="chrome_cdp_fp_default.png",
        size=(800, 600),
        full_page=True,
    )
    p2 = hti.screenshot(
        html_str=_SHORT_CARD_HTML,
        save_as="chrome_cdp_fp_robust.png",
        size=(800, 600),
        full_page=True,
        full_page_profile='robust',
    )
    assert Image.open(p1[0]).size[1] == Image.open(p2[0]).size[1]


@pytest.mark.parametrize("profile", ["robust", "balanced", "fast"])
def test_firefox_bidi_full_page_profiles_short_card(profile):
    """Smoke test Firefox : tous les profils capturent correctement une page statique."""
    hti = _make_hti("firefox-bidi")
    paths = hti.screenshot(
        html_str=_SHORT_CARD_HTML,
        save_as=f"firefox_bidi_full_page_{profile}_short.png",
        size=(800, 600),
        full_page=True,
        full_page_profile=profile,
    )
    img = Image.open(paths[0])
    assert img.width == 800
    assert img.height > 600
    assert img.height < 1200


def test_firefox_bidi_full_page_robust_default_unchanged():
    """Non-regression Firefox : defaut sans parametre == robust explicite."""
    hti = _make_hti("firefox-bidi")
    p1 = hti.screenshot(
        html_str=_SHORT_CARD_HTML,
        save_as="firefox_bidi_fp_default.png",
        size=(800, 600),
        full_page=True,
    )
    p2 = hti.screenshot(
        html_str=_SHORT_CARD_HTML,
        save_as="firefox_bidi_fp_robust.png",
        size=(800, 600),
        full_page=True,
        full_page_profile='robust',
    )
    assert Image.open(p1[0]).size[1] == Image.open(p2[0]).size[1]
