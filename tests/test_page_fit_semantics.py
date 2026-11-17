"""Semantic browser checks for the public full-page contract."""

from pathlib import Path
import warnings

import pytest
from PIL import Image

from html2image import CaptureTooLargeError, FullPageWarning, Html2Image


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

    # The page does not move: no seam is left unchecked, even if an element
    # becomes fixed.
    with warnings.catch_warnings():
        warnings.simplefilter("error", FullPageWarning)
        output = hti.screenshot(
            html_str=(
                '<!doctype html><body style="margin:0; height:2500px">'
                # An ordinary fixed element, so that the page is captured in
                # tiles.
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


def _sticky_only_html(height=2500):
    return """<!doctype html>
<style>
  html, body { margin: 0; }
  .before { height: 900px; }
  .sticky { position: sticky; top: 0; height: 20px; background: #ff00ff; }
  .after { height: %dpx; }
</style>
<div class="before"></div><div class="sticky"></div><div class="after"></div>
""" % (height - 920)


@pytest.mark.parametrize(
    "browser", ["chrome-cdp", "firefox-bidi"], ids=["chrome", "firefox"]
)
@pytest.mark.parametrize("mode", ["auto", "first", "last", "hide"])
# Chrome captures the longer page in tiles in every mode.
@pytest.mark.parametrize("height", [2500, 17000])
def test_full_page_keeps_sticky_at_its_natural_position(
    browser, mode, height, tmp_path
):
    pytest.importorskip("pyvips")
    hti = _make_hti(browser, tmp_path)

    output = hti.screenshot(
        html_str=_sticky_only_html(height),
        save_as="sticky-%s.png" % mode,
        size=(400, 600),
        full_page=True,
        full_page_profile="fast",
        full_page_fixed_elements=mode,
    )[0]

    magenta_rows, size = _rows_with_color(output, (255, 0, 255))
    assert size == (400, height)
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

        state = hti.browser._evaluate(
            """(() => {
              const el = document.querySelector('.top');
              return JSON.stringify({
                scrollY: Math.round(scrollY),
                inlineVisibility: el.style.visibility,
                position: getComputedStyle(el).position
              });
            })()"""
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
    from html2image.browsers import _page_fit_common as page_fit

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


@TILED_BROWSERS
@pytest.mark.parametrize("profile", ["fast", "balanced"])
def test_full_page_of_an_svg_file(browser, profile, tmp_path):
    hti = _make_hti(browser, tmp_path)

    output = hti.screenshot(
        other_file="./examples/star.svg",
        save_as="star.png",
        size=(400, 300),
        full_page=True,
        full_page_profile=profile,
    )[0]

    with Image.open(output) as image:
        assert image.width == 400
        assert image.height >= 300


@TILED_BROWSERS
def test_full_page_that_fits_in_the_viewport_does_not_resize_it(
    browser, tmp_path
):
    hti = _make_hti(browser, tmp_path)

    output = hti.screenshot(
        html_str=(
            '<!doctype html><body style="margin:0; background:#00ff00">'
            "<script>addEventListener('resize', () =>"
            " document.body.style.background = '#ff0000');</script>"
        ),
        save_as="fits.png",
        size=(400, 600),
        full_page=True,
        full_page_profile="fast",
    )[0]

    # The page would turn red after a resize event.
    with Image.open(output) as image:
        rgb = image.convert("RGB")
    assert rgb.size == (400, 600)
    assert rgb.getpixel((200, 300)) == (0, 255, 0)


@TILED_BROWSERS
# What is left for the last tile is shorter than the banner.
@pytest.mark.parametrize("height", [700, 1250, 1300])
def test_full_page_auto_shows_a_bottom_banner_whole(browser, height, tmp_path):
    pytest.importorskip("pyvips")
    hti = _make_hti(browser, tmp_path)

    output = hti.screenshot(
        html_str=(
            '<!doctype html><body style="margin:0; height:%dpx;'
            ' background:#eeeeee"><div style="position:fixed; bottom:0;'
            ' left:0; width:100%%; height:200px; background:#0000ff"></div>'
            % height
        ),
        save_as="bottom-banner.png",
        size=(400, 600),
        full_page=True,
        full_page_profile="fast",
    )[0]

    blue_rows, size = _rows_with_color(output, (0, 0, 255))
    assert size == (400, height)
    assert blue_rows == list(range(height - 200, height))


@TILED_BROWSERS
def test_tiles_stop_following_an_endless_feed(browser, tmp_path):
    pytest.importorskip("pyvips")
    hti = _make_hti(browser, tmp_path)

    # Never without a pixel budget: the page would grow until the memory of
    # the machine is used up, if the tiles followed it.
    with pytest.warns(FullPageWarning, match="kept growing"):
        output = hti.screenshot(
            html_str=(
                '<!doctype html><body style="margin:0"><div id="feed"></div>'
                "%s<script>const add = () => feed.appendChild("
                "Object.assign(document.createElement('div'),"
                " {style: 'height:600px; background:#808080'}));"
                "add(); add(); add(); addEventListener('scroll', () => {"
                " if (scrollY + innerHeight >= document.documentElement"
                ".scrollHeight - 50) add(); });</script>" % _BADGE
            ),
            save_as="endless.png",
            size=(400, 600),
            full_page=True,
            full_page_profile="fast",
            full_page_max_pixels=400 * 30_000,
        )[0]

    # The feed was 1800 px high when the tiles started.
    with Image.open(output) as image:
        assert image.size == (400, 1800 + 10 * 600)


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


def _spaced_bands_html(boxes):
    """Returns a page with a header of 100 px that grows to 200 px once the
    page is scrolled, then 30 bands of 80 px, each of its own color and
    made of `boxes` boxes side by side, with 20 px between them. All of
    them are in one element, which is all there is between the bands."""
    bands = "".join(
        '<div class="band">%s</div>'
        % ('<div style="background:rgb%s"></div>' % (_band_color(index),)
           * boxes)
        for index in range(30)
    )
    return (
        "<!doctype html><style>.band { display:flex; height:80px;"
        " margin-bottom:20px } .band div { flex:1 }</style>"
        '<body style="margin:0; background:#ffffff"><div>'
        '<header id="header" style="height:100px; background:#282828">'
        "</header>%s</div>%s<script>addEventListener('scroll', () =>"
        " header.style.height = scrollY > 0 ? '200px' : '100px');"
        "</script>" % (bands, _BADGE)
    )


@TILED_BROWSERS
# With a single box, the band above a seam is its only anchor, and the
# bands above it are its backup anchors.
@pytest.mark.parametrize("boxes", [4, 1])
def test_tiles_follow_a_page_that_moves_between_its_seams(
    browser, boxes, tmp_path
):
    pytest.importorskip("pyvips")
    hti = _make_hti(browser, tmp_path)

    with warnings.catch_warnings():
        warnings.simplefilter("error", FullPageWarning)
        output = hti.screenshot(
            html_str=_spaced_bands_html(boxes),
            save_as="spaced-bands.png",
            size=(400, 600),
            full_page=True,
            full_page_profile="fast",
        )[0]

    # The seams are between two bands, where the only element under the
    # seam is the one around all of them, which does not move with them.
    with Image.open(output) as image:
        rgb = image.convert("RGB")
    assert rgb.size == (400, 3100)
    for index in range(30):
        top = 100 + index * 100
        for y in (top + 1, top + 78):
            assert rgb.getpixel((10, y)) == _band_color(index), (index, y)
        assert rgb.getpixel((10, top + 90)) == (255, 255, 255), index


def _blocks_html(content, script):
    """Returns a page of 20 blocks as wide as the page, of 100 px, each of
    its own color, 20 px apart, the first one 10 px from the top. The fifth
    one, `moving`, ends 10 px above the seam at 600 px. It holds `content`,
    and `script` changes it once the page is scrolled. The others hold 4
    boxes side by side, so that there are several backup anchors."""
    boxes = '<div style="display:flex; height:100%%">%s</div>' % (
        '<div style="flex:1"></div>' * 4
    )
    blocks = "".join(
        '<div %s style="position:relative; margin-top:%dpx; height:100px;'
        ' background:rgb%s">%s</div>'
        % ('id="moving"' if index == 4 else "", 20 if index else 10,
           _band_color(index), content if index == 4 else boxes)
        for index in range(20)
    )
    return (
        '<!doctype html><body style="margin:0; background:#ffffff">%s%s'
        "<script>addEventListener('scroll', () => { if (scrollY > 0) %s })"
        "</script>" % (blocks, _BADGE, script)
    )


@TILED_BROWSERS
def test_tiles_warn_when_a_block_grows_above_a_seam(browser, tmp_path):
    pytest.importorskip("pyvips")
    hti = _make_hti(browser, tmp_path)

    # The block is the only anchor of the seam. It moved, but the blocks
    # above it did not: the page did not move with it.
    with pytest.warns(FullPageWarning):
        hti.screenshot(
            html_str=_blocks_html("", "moving.style.height = '112px';"),
            save_as="growing-block.png",
            size=(400, 600),
            full_page=True,
            full_page_profile="fast",
        )


@TILED_BROWSERS
def test_tiles_do_not_follow_a_block_that_moves_by_itself(browser, tmp_path):
    pytest.importorskip("pyvips")
    hti = _make_hti(browser, tmp_path)

    # The last box of the block shares its bottom edge, and is the anchor.
    # The first one moves with the block: it does not tell that the page
    # moved.
    content = (
        '<div style="height:30px; background:#000000"></div>'
        '<div style="height:70px"></div>'
    )
    with pytest.warns(FullPageWarning, match="moved unevenly"):
        output = hti.screenshot(
            html_str=_blocks_html(content, "moving.style.top = '12px';"),
            save_as="moving-block.png",
            size=(400, 600),
            full_page=True,
            full_page_profile="fast",
        )[0]

    with Image.open(output) as image:
        rgb = image.convert("RGB")
    assert rgb.getpixel((10, 605)) == (255, 255, 255)
    assert rgb.getpixel((10, 611)) == _band_color(5)


# A page without anything but a fixed badge, which is not an anchor.
_EMPTY_HTML = (
    '<!doctype html><body style="margin:0; height:4000px">%s<script>%%s'
    "</script>" % _BADGE
)


@TILED_BROWSERS
def test_tiles_of_a_still_page_without_anchors(browser, tmp_path):
    pytest.importorskip("pyvips")
    hti = _make_hti(browser, tmp_path)

    with warnings.catch_warnings():
        warnings.simplefilter("error", FullPageWarning)
        output = hti.screenshot(
            html_str=_EMPTY_HTML % "",
            save_as="empty.png",
            size=(400, 600),
            full_page=True,
            full_page_profile="fast",
        )[0]

    with Image.open(output) as image:
        assert image.size == (400, 4000)


@TILED_BROWSERS
def test_tiles_warn_when_a_page_without_anchors_grows(browser, tmp_path):
    pytest.importorskip("pyvips")
    hti = _make_hti(browser, tmp_path)

    with pytest.warns(FullPageWarning, match="could not be checked"):
        hti.screenshot(
            html_str=_EMPTY_HTML % (
                "addEventListener('scroll', () =>"
                " document.body.style.height = '4100px');"
            ),
            save_as="empty.png",
            size=(400, 600),
            full_page=True,
            full_page_profile="fast",
        )


@TILED_BROWSERS
def test_tiles_warn_when_a_single_column_moves(browser, tmp_path):
    pytest.importorskip("pyvips")
    hti = _make_hti(browser, tmp_path)
    left = "".join(
        '<div style="display:flex; height:100px">%s</div>'
        % ('<div style="flex:1; background:rgb%s"></div>'
           % (_band_color(index),) * 2)
        for index in range(30)
    )
    right = "".join(
        '<div style="height:100px; background:rgb%s"></div>'
        % (_band_color(index),)
        for index in range(30)
    )

    with pytest.warns(FullPageWarning, match="unevenly"):
        hti.screenshot(
            html_str=(
                '<!doctype html><body style="margin:0">'
                '<div style="display:flex; align-items:flex-start">'
                '<div style="width:60%%"><div id="spacer"></div>%s</div>'
                '<div style="width:40%%">%s</div></div>%s<script>'
                "addEventListener('scroll', () =>"
                " spacer.style.height = scrollY > 0 ? '12px' : '0');"
                "</script>" % (left, right, _BADGE)
            ),
            save_as="one-column.png",
            size=(400, 600),
            full_page=True,
            full_page_profile="fast",
        )


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


def test_firefox_stops_where_a_page_cannot_be_scrolled(tmp_path):
    pytest.importorskip("pyvips")
    hti = _make_hti("firefox-bidi", tmp_path)

    # Firefox only captures what the viewport shows.
    with pytest.warns(FullPageWarning, match="further than 600 px"):
        output = hti.screenshot(
            html_str=_bands_html(
                "addEventListener('scroll', () => scrollTo(0, 0));"
            ),
            save_as="not-scrolled.png",
            size=(400, 600),
            full_page=True,
            full_page_profile="fast",
        )[0]

    with Image.open(output) as image:
        rgb = image.convert("RGB")
    assert rgb.size == (400, 600)
    assert rgb.getpixel((10, 101)) == _band_color(0)
    assert rgb.getpixel((10, 598)) == _band_color(4)


@TILED_BROWSERS
@pytest.mark.parametrize("badge", ["", _BADGE], ids=["alone", "fixed"])
def test_full_page_of_a_page_that_scrolls_inside_its_body(
    browser, badge, tmp_path
):
    hti = _make_hti(browser, tmp_path)
    blocks = "".join(
        '<div style="height:500px; background:rgb%s"></div>'
        % (_band_color(index),)
        for index in range(10)
    )

    # The window cannot scroll: the image is what it shows.
    with pytest.warns(FullPageWarning, match="scrolls inside its body"):
        output = hti.screenshot(
            html_str=(
                "<!doctype html><style>html { height:100%%;"
                " overflow:hidden; margin:0 } body { height:100%%;"
                " overflow:auto; margin:0 }</style>%s%s" % (blocks, badge)
            ),
            save_as="inner-scroll.png",
            size=(400, 600),
            full_page=True,
            full_page_profile="fast",
        )[0]

    with Image.open(output) as image:
        rgb = image.convert("RGB")
    assert rgb.size == (400, 600)
    assert rgb.getpixel((10, 10)) == _band_color(0)
    assert rgb.getpixel((10, 550)) == _band_color(1)


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
