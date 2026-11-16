"""Semantic browser checks for the public full-page contract."""

from pathlib import Path

import pytest
from PIL import Image

from html2image import CaptureTooLargeError, Html2Image


def _make_hti(browser, output_path):
    try:
        return Html2Image(
            browser=browser,
            output_path=str(output_path),
            disable_logging=True,
        )
    except FileNotFoundError:
        pytest.skip(f"{browser!r} executable not found")


def _responsive_cards_html(card_count=30):
    cards = "".join(f"<article>Card {index}</article>" for index in range(card_count))
    return f"""<!doctype html>
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; }}
  .cards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }}
  article {{ height: 180px; background: #dceaf2; }}
  @media (max-width: 700px) {{
    .cards {{ grid-template-columns: 1fr; }}
    article {{ background: #f4d99b; }}
  }}
</style>
<div class="cards">{cards}</div>
"""


@pytest.mark.parametrize(
    "browser", ["chrome-cdp", "firefox-bidi"], ids=["chrome", "firefox"]
)
def test_full_page_uses_requested_responsive_viewport(browser, tmp_path):
    hti = _make_hti(browser, tmp_path)
    html = _responsive_cards_html()

    with hti:
        desktop = hti.screenshot(
            html_str=html,
            save_as="desktop.png",
            size=(1280, 720),
            full_page=True,
            full_page_profile="fast",
        )[0]
        mobile = hti.screenshot(
            html_str=html,
            save_as="mobile.png",
            size=(375, 667),
            full_page=True,
            full_page_profile="fast",
        )[0]

    with Image.open(desktop) as desktop_image, Image.open(mobile) as mobile_image:
        assert desktop_image.width == 1280
        assert mobile_image.width == 375
        assert mobile_image.height > desktop_image.height * 2


@pytest.mark.parametrize(
    "browser",
    ["chrome-cdp", "edge-cdp", "firefox-bidi"],
    ids=["chrome", "edge", "firefox"],
)
def test_full_page_jpeg_matches_its_extension(browser, tmp_path):
    hti = _make_hti(browser, tmp_path)
    output = hti.screenshot(
        html_str=(
            '<body style="margin:0;height:900px;background:#30a060"></body>'
        ),
        save_as="full-page.jpg",
        size=(640, 360),
        full_page=True,
        full_page_profile="fast",
    )[0]

    with Image.open(output) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert image.size == (640, 900)


@pytest.mark.parametrize(
    "browser", ["chrome-cdp", "firefox-bidi"], ids=["chrome", "firefox"]
)
def test_full_page_pixel_budget_fails_without_output(browser, tmp_path):
    hti = _make_hti(browser, tmp_path)
    destination = Path(tmp_path) / "over-budget.png"

    with pytest.raises(
        CaptureTooLargeError, match="full_page_max_pixels"
    ) as error:
        hti.screenshot(
            html_str='<body style="height:900px"></body>',
            save_as=destination.name,
            size=(640, 360),
            full_page=True,
            full_page_profile="fast",
            full_page_max_pixels=1_000,
        )

    assert not destination.exists()
    assert error.value.paths == []
    assert error.value.too_large == [(None, destination.name)]


@pytest.mark.parametrize(
    "browser", ["chrome-cdp", "firefox-bidi"], ids=["chrome", "firefox"]
)
def test_full_page_without_doctype(browser, tmp_path):
    # Without a doctype, the page is rendered in quirks mode, where the
    # root element can be smaller than the page.
    hti = _make_hti(browser, tmp_path)
    hti.add_doctype = False
    output = hti.screenshot(
        html_str='<div style="height:1500px;background:#30a060"></div>',
        css_str="body { margin: 0; }",
        save_as="quirks.png",
        size=(640, 360),
        full_page=True,
        full_page_profile="fast",
    )[0]

    with Image.open(output) as image:
        assert image.size == (640, 1500)
        assert image.convert("RGB").getpixel((320, 1400)) == (48, 160, 96)


def _fixed_overlay_html():
    return """<!doctype html>
<style>
  html { scroll-behavior: smooth; }
  html, body { margin: 0; }
  body { height: 2500px; background: #eeeeee; }
  .top, .bottom {
    position: fixed; left: 0; width: 100%; height: 20px; z-index: 9;
  }
  .top { top: 0; background: #ff0000; }
  .bottom { bottom: 0; background: #0000ff; }
  .hidden {
    position: fixed; inset: 100px 0 auto; height: 20px;
    visibility: hidden; background: #00ff00;
  }
</style>
<div class="top"></div><div class="bottom"></div><div class="hidden"></div>
"""


def _rows_with_color(path, color):
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        return [
            y for y in range(rgb.height)
            if rgb.getpixel((rgb.width // 2, y)) == color
        ], rgb.size


@pytest.mark.parametrize(
    "browser", ["chrome-cdp", "firefox-bidi"], ids=["chrome", "firefox"]
)
def test_full_page_fixed_element_policies(browser, tmp_path):
    pytest.importorskip("pyvips")
    hti = _make_hti(browser, tmp_path)
    viewport_height = 600
    outputs = {}

    with hti:
        for mode in ("auto", "first", "last", "hide"):
            outputs[mode] = hti.screenshot(
                html_str=_fixed_overlay_html(),
                save_as=f"fixed-{mode}.png",
                size=(400, viewport_height),
                full_page=True,
                full_page_profile="fast",
                full_page_fixed_elements=mode,
            )[0]

    red = (255, 0, 0)
    blue = (0, 0, 255)
    auto_red, size = _rows_with_color(outputs["auto"], red)
    auto_blue, _ = _rows_with_color(outputs["auto"], blue)
    auto_hidden, _ = _rows_with_color(outputs["auto"], (0, 255, 0))
    assert auto_red == list(range(20))
    assert auto_blue == list(range(size[1] - 20, size[1]))
    assert auto_hidden == []

    first_red, _ = _rows_with_color(outputs["first"], red)
    first_blue, _ = _rows_with_color(outputs["first"], blue)
    assert first_red == list(range(20))
    assert first_blue == list(range(viewport_height - 20, viewport_height))

    last_red, _ = _rows_with_color(outputs["last"], red)
    last_blue, _ = _rows_with_color(outputs["last"], blue)
    assert last_red == list(
        range(size[1] - viewport_height, size[1] - viewport_height + 20)
    )
    assert last_blue == list(range(size[1] - 20, size[1]))

    hidden_red, _ = _rows_with_color(outputs["hide"], red)
    hidden_blue, _ = _rows_with_color(outputs["hide"], blue)
    assert hidden_red == []
    assert hidden_blue == []


_HARD_TO_HIDE_FIXED_ELEMENTS = {
    # A descendant can opt out of the `visibility` of its fixed ancestor.
    "visible-descendant": """
<div style="position:fixed; top:0; left:0; width:100%; height:20px">
  <div style="visibility:visible; height:20px; background:#ff0000"></div>
</div>""",
    # The fixed element itself has no height, its content overflows.
    "empty-container": """
<div style="position:fixed; top:0; left:0; width:100%; height:0">
  <div style="height:20px; background:#ff0000"></div>
</div>""",
    # The element only becomes fixed once the page is scrolled.
    "fixed-on-scroll": """
<div id="bar" style="position:absolute; top:0; left:0; width:100%;
                     height:20px; background:#ff0000"></div>
<script>
  addEventListener('scroll', () => {
    bar.style.position = scrollY > 0 ? 'fixed' : 'absolute';
  });
</script>""",
}


@pytest.mark.parametrize(
    "browser", ["chrome-cdp", "firefox-bidi"], ids=["chrome", "firefox"]
)
@pytest.mark.parametrize("case", list(_HARD_TO_HIDE_FIXED_ELEMENTS))
def test_full_page_auto_shows_fixed_element_once(browser, case, tmp_path):
    pytest.importorskip("pyvips")
    hti = _make_hti(browser, tmp_path)

    output = hti.screenshot(
        html_str=(
            '<!doctype html><body style="margin:0; height:2500px">'
            # An ordinary fixed element, so that the page is captured in tiles.
            '<div style="position:fixed; bottom:0; left:0; width:100%;'
            ' height:20px; background:#0000ff"></div>'
            + _HARD_TO_HIDE_FIXED_ELEMENTS[case]
        ),
        save_as=f"fixed-once-{case}.png",
        size=(400, 600),
        full_page=True,
        full_page_profile="fast",
    )[0]

    red_rows, size = _rows_with_color(output, (255, 0, 0))
    assert size == (400, 2500)
    assert red_rows == list(range(20))


def _sticky_only_html():
    return """<!doctype html>
<style>
  html, body { margin: 0; }
  .before { height: 900px; }
  .sticky { position: sticky; top: 0; height: 20px; background: #ff00ff; }
  .after { height: 1580px; }
</style>
<div class="before"></div><div class="sticky"></div><div class="after"></div>
"""


@pytest.mark.parametrize(
    "browser", ["chrome-cdp", "firefox-bidi"], ids=["chrome", "firefox"]
)
def test_full_page_auto_keeps_sticky_at_its_natural_position(browser, tmp_path):
    pytest.importorskip("pyvips")
    hti = _make_hti(browser, tmp_path)

    output = hti.screenshot(
        html_str=_sticky_only_html(),
        save_as="sticky-auto.png",
        size=(400, 600),
        full_page=True,
        full_page_profile="fast",
        full_page_fixed_elements="auto",
    )[0]

    magenta_rows, size = _rows_with_color(output, (255, 0, 255))
    assert size == (400, 2500)
    assert magenta_rows == list(range(900, 920))


def _reserved_lazy_html():
    return """<!doctype html>
<style>
  html, body { margin: 0; }
  .before { height: 3600px; }
  #target { height: 100px; background: #808080; }
  .after { height: 8300px; }
</style>
<div class="before"></div><div id="target"></div><div class="after"></div>
<script>
  const target = document.getElementById('target');
  new IntersectionObserver((entries) => {
    if (entries.some((entry) => entry.isIntersecting)) {
      target.style.background = '#ff00ff';
    }
  }).observe(target);
</script>
"""


@pytest.mark.parametrize(
    "browser", ["chrome-cdp", "firefox-bidi"], ids=["chrome", "firefox"]
)
def test_full_page_robust_triggers_lazy_content_with_reserved_height(
    browser, tmp_path
):
    hti = _make_hti(browser, tmp_path)
    output = hti.screenshot(
        html_str=_reserved_lazy_html(),
        save_as="reserved-lazy.png",
        size=(400, 600),
        full_page=True,
        full_page_profile="robust",
    )[0]

    with Image.open(output) as image:
        rgb = image.convert("RGB")
        assert rgb.size == (400, 12000)
        assert rgb.getpixel((200, 3650)) == (255, 0, 255)


def test_chromium_full_page_png_preserves_transparency(tmp_path):
    hti = _make_hti("chrome-cdp", tmp_path)
    output = hti.screenshot(
        html_str=(
            '<body style="margin:0;height:900px;background:transparent">'
            '<div style="width:20px;height:20px;background:#ff0000"></div>'
            '</body>'
        ),
        save_as="transparent.png",
        size=(400, 600),
        full_page=True,
        full_page_profile="fast",
    )[0]

    with Image.open(output) as image:
        rgba = image.convert("RGBA")
        assert rgba.size == (400, 900)
        assert rgba.getpixel((10, 10)) == (255, 0, 0, 255)
        assert rgba.getpixel((200, 450))[3] == 0


def _growing_during_tiling_html():
    return """<!doctype html>
<style>
  html, body { margin: 0; }
  body { height: 2500px; }
  .top { position: fixed; top: 0; width: 100%; height: 20px; background: red; }
</style>
<div class="top"></div>
<script>
  let grown = false;
  addEventListener('scroll', () => {
    if (!grown && scrollY > 0) {
      grown = true;
      document.body.style.height = '3000px';
    }
  });
</script>
"""


@pytest.mark.parametrize(
    "browser", ["chrome-cdp", "firefox-bidi"], ids=["chrome", "firefox"]
)
def test_full_page_follows_growth_during_tiling_and_restores_page(
    browser, tmp_path
):
    pytest.importorskip("pyvips")
    hti = _make_hti(browser, tmp_path)
    destination = Path(tmp_path) / "grew-during-tiling.png"

    with hti:
        hti.screenshot(
            html_str=_growing_during_tiling_html(),
            save_as=destination.name,
            size=(400, 600),
            full_page=True,
            full_page_profile="fast",
            full_page_fixed_elements="last",
        )

        if browser == "chrome-cdp":
            from html2image.browsers import _chromium_page_fit as page_fit
        else:
            from html2image.browsers import _firefox_page_fit as page_fit
        state = page_fit._evaluate(
            hti.browser,
            """(() => {
              const el = document.querySelector('.top');
              return {
                scrollY: Math.round(scrollY),
                inlineVisibility: el.style.visibility,
                position: getComputedStyle(el).position
              };
            })()""",
        )

    assert state == {
        "scrollY": 0,
        "inlineVisibility": "",
        "position": "fixed",
    }
    with Image.open(destination) as image:
        assert image.size == (400, 3000)


@pytest.mark.parametrize(
    "browser", ["chrome-cdp", "firefox-bidi"], ids=["chrome", "firefox"]
)
def test_short_fixed_page_does_not_require_the_optional_stitcher(
    browser, tmp_path, monkeypatch
):
    if browser == "chrome-cdp":
        from html2image.browsers import _chromium_page_fit as page_fit
    else:
        from html2image.browsers import _firefox_page_fit as page_fit

    def fail_if_stitching_is_attempted():
        raise AssertionError("the short native capture must not import pyvips")

    monkeypatch.setattr(
        page_fit,
        "import_pyvips_for_stitching",
        fail_if_stitching_is_attempted,
    )
    hti = _make_hti(browser, tmp_path)
    output = hti.screenshot(
        html_str="""<!doctype html>
        <style>
          html, body { margin: 0; height: 100%; }
          header { position: fixed; top: 0; height: 20px; width: 100%; }
        </style><header></header>""",
        save_as="short-fixed-native.png",
        size=(400, 600),
        full_page=True,
        full_page_profile="fast",
    )[0]

    with Image.open(output) as image:
        assert image.size == (400, 600)


TILED_BROWSERS = pytest.mark.parametrize(
    "browser",
    ["chrome-cdp", "edge-cdp", "firefox-bidi"],
    ids=["chrome", "edge", "firefox"],
)

# A small fixed badge, so that the page is captured in tiles.
_BADGE = (
    '<div style="position:fixed; bottom:0; right:0; width:20px;'
    ' height:20px; background:#0000ff"></div>'
)


def _band_color(index):
    return (index * 8, 255 - index * 8, 128)


def _bands_html(script=""):
    """Returns a page with a header of 100 px, then 30 bands of 100 px,
    each of its own color, and made of 4 boxes side by side."""
    bands = "".join(
        '<div class="band">%s</div>'
        % ('<div style="background:rgb%s"></div>' % (_band_color(index),) * 4)
        for index in range(30)
    )
    return (
        "<!doctype html><style>.band { display:flex; height:100px }"
        " .band div { flex:1 }</style>"
        '<body style="margin:0">'
        '<header id="header" style="height:100px; background:#282828">'
        "</header>%s%s<script>%s</script>" % (bands, _BADGE, script)
    )


def _assert_bands(path, header_height=100):
    with Image.open(path) as image:
        rgb = image.convert("RGB")
    assert rgb.size == (400, header_height + 3000)
    for index in range(30):
        top = header_height + index * 100
        for y in (top + 1, top + 98):
            assert rgb.getpixel((10, y)) == _band_color(index), (index, y)


@TILED_BROWSERS
def test_tiles_do_not_resize_the_page(browser, tmp_path):
    pytest.importorskip("pyvips")
    hti = _make_hti(browser, tmp_path)

    output = hti.screenshot(
        html_str=_bands_html(
            "addEventListener('resize', () =>"
            " document.body.style.filter = 'invert(1)');"
        ),
        save_as="no-resize.png",
        size=(400, 600),
        full_page=True,
        full_page_profile="fast",
    )[0]

    # The colors would be inverted after the first resize event.
    _assert_bands(output)


@TILED_BROWSERS
@pytest.mark.parametrize("profile", ["fast", "balanced"])
def test_tiles_follow_a_header_that_shrinks_when_scrolled(
    browser, profile, tmp_path
):
    pytest.importorskip("pyvips")
    hti = _make_hti(browser, tmp_path)

    output = hti.screenshot(
        html_str=_bands_html(
            "addEventListener('scroll', () =>"
            " header.style.height = scrollY > 0 ? '80px' : '100px');"
        ),
        save_as="shrinking-header.png",
        size=(400, 600),
        full_page=True,
        full_page_profile=profile,
    )[0]

    # The first tile shows the header before it shrinks, and the next
    # tiles start 20 px higher, where the page moved.
    _assert_bands(output)


def test_tiles_of_a_page_that_cannot_be_scrolled(tmp_path):
    pytest.importorskip("pyvips")
    hti = _make_hti("chrome-cdp", tmp_path)

    output = hti.screenshot(
        html_str=_bands_html(
            "addEventListener('scroll', () => scrollTo(0, 0));"
        ),
        save_as="not-scrolled.png",
        size=(400, 600),
        full_page=True,
        full_page_profile="fast",
    )[0]

    # The tiles below the viewport are captured beyond it.
    _assert_bands(output)


def test_tiles_with_virtual_time_budget(tmp_path):
    pytest.importorskip("pyvips")
    try:
        hti = Html2Image(
            browser="chrome-cdp",
            output_path=str(tmp_path),
            disable_logging=True,
            custom_flags=["--virtual-time-budget=1000", "--hide-scrollbars"],
        )
    except FileNotFoundError:
        pytest.skip("'chrome-cdp' executable not found")

    for profile in ("fast", "robust"):
        output = hti.screenshot(
            html_str=_bands_html(
                # Shown once the virtual time budget is spent.
                "setTimeout(() => header.style.background = '#ff0000', 500);"
            ),
            save_as=f"virtual-time-{profile}.png",
            size=(400, 600),
            full_page=True,
            full_page_profile=profile,
        )[0]

        _assert_bands(output)
        with Image.open(output) as image:
            assert image.convert("RGB").getpixel((10, 50)) == (255, 0, 0)
