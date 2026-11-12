from html2image import Html2Image
from PIL import Image, ImageChops

import pytest
import os

OUTPUT_PATH = "tests_output"
os.makedirs(OUTPUT_PATH, exist_ok=True)

TEST_BROWSERS = ["edGe", "cHrOme"]
ISSUE177_BROWSERS = ["chrome", "chrome-cdp"]


def _is_red(rgba):
    r, g, b, a = rgba
    return a > 180 and r >= 170 and g <= 95 and b <= 95


def _strip_metrics(img):
    rgba_img = img.convert("RGBA")
    w, h = rgba_img.size
    cx = w // 2
    cy = h // 2

    max_red_y = -1
    for y in range(h):
        if _is_red(rgba_img.getpixel((cx, y))):
            max_red_y = y

    max_red_x = -1
    for x in range(w):
        if _is_red(rgba_img.getpixel((x, cy))):
            max_red_x = x

    bottom_strip = h - (max_red_y + 1)
    right_strip = w - (max_red_x + 1)
    return max(0, bottom_strip), max(0, right_strip)

def test_bad_browser():
    with pytest.raises(ValueError):
        Html2Image(browser='watergoupil')

@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_good_browser(browser):
    Html2Image(browser=browser)


def test_chrome_headless_alias_maps_to_legacy_backend():
    hti = Html2Image(browser='chrome-headless')
    assert type(hti.browser).__name__ == 'ChromeHeadless'


def test_cdp_port_forwarded():
    hti = Html2Image(browser='chrome-cdp', browser_cdp_port=9555)
    assert hti.browser.cdp_port == 9555


def test_cdp_port_forwarded_for_default_chrome_backend():
    hti = Html2Image(browser='chrome', browser_cdp_port=9555)
    assert hti.browser.cdp_port == 9555


def test_screenshot_string_chrome_cdp():
    hti = Html2Image(
        browser='chrome-cdp',
        output_path=OUTPUT_PATH,
        disable_logging=True,
    )

    paths = hti.screenshot(
        html_str='Hello from CDP',
        save_as='cdp_hello.png',
        size=(320, 240),
    )

    img = Image.open(paths[0])
    assert (320, 240) == img.size


@pytest.mark.parametrize("browser", ISSUE177_BROWSERS)
def test_issue177_exact_size_contract(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)
    paths = hti.screenshot(
        html_str='<body style="margin:0;background:green"></body>',
        save_as=f'issue177_size_{browser}.png',
        size=(800, 480),
    )
    img = Image.open(paths[0])
    assert img.size == (800, 480)


@pytest.mark.parametrize("browser", ISSUE177_BROWSERS)
def test_issue177_no_bottom_strip_100vh(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)
    paths = hti.screenshot(
        html_str=(
            '<style>html,body{margin:0;padding:0;overflow:hidden;}'
            '#fill{width:100vw;height:100vh;background:#ff0000;}</style>'
            '<div id="fill"></div>'
        ),
        save_as=f'issue177_viewport_{browser}.png',
        size=(800, 480),
    )

    img = Image.open(paths[0])
    assert img.size == (800, 480)
    bottom_strip, right_strip = _strip_metrics(img)
    assert bottom_strip <= 2
    assert right_strip <= 2


@pytest.mark.parametrize("browser", ISSUE177_BROWSERS)
def test_issue177_svg_transparent_background(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)
    paths = hti.screenshot(
        other_file='./examples/star.svg',
        save_as=f'issue177_svg_alpha_{browser}.png',
        size=(500, 500),
    )

    img = Image.open(paths[0]).convert("RGBA")
    assert img.size == (500, 500)
    assert img.getpixel((0, 0))[3] == 0


@pytest.mark.parametrize("browser", ISSUE177_BROWSERS)
def test_issue177_jpg_output_format(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)
    paths = hti.screenshot(
        html_str='<body style="margin:0;background:#00aa00"></body>',
        save_as=f'issue177_jpg_{browser}.jpg',
        size=(640, 360),
    )

    img = Image.open(paths[0])
    assert img.size == (640, 360)
    assert img.format == "JPEG"

@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_url(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    paths = hti.screenshot(url='https://www.python.org', save_as="pyorg.png")
    img = Image.open(paths[0])
    assert (1920, 1080) == img.size  # default size

@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_multiple_urls(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)
    paths = hti.screenshot(
        url=['https://www.python.org', "https://www.example.org/"],
        save_as="mixed_urls.png",
    )

    for path in paths:
        img = Image.open(path)
        assert (1920, 1080) == img.size  # default size

@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_url_custom_size(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    test_size = (334, 485)

    paths = hti.screenshot(
        url='https://www.python.org',
        save_as="pyorg_custom_size.png",
        size=test_size,
    )

    img = Image.open(paths[0])
    assert test_size == img.size  # default size

@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_url_custom_sizes(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    test_sizes = [
        (100, 100),
        (100, 1000),
        (100, 200),
    ]

    paths = hti.screenshot(
        url=[
            'https://www.python.org',
            'https://www.wikipedia.org/',
            'https://www.example.org/',
        ],
        save_as="mixed_urls_custom_sizes.png",
        size=test_sizes,
    )

    for wanted_size, path in zip(test_sizes, paths):
        img = Image.open(path)
        assert wanted_size == img.size

@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_url_sizes_missing_custom_names(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    test_sizes = [
        (100, 100),
        (100, 1000),
    ]

    paths = hti.screenshot(
        url=[
            'https://www.python.org',
            'https://www.wikipedia.org/',
            'https://www.example.org/',
        ],
        save_as=[
            "python_100_100.png",
            "wikipedia_100_1000.png",
            "example_100_1000.png",
        ],
        size=test_sizes,
    )
    effective_wanted_sizes = test_sizes + [test_sizes[-1]]
    for wanted_size, path in zip(effective_wanted_sizes, paths):
        img = Image.open(path)
        assert wanted_size == img.size

@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_string(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

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

@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_string_different_sizes(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    test_sizes = [
        (100, 100),
        (100, 1000),
        (100, 200),
    ]

    html = "Hello"

    paths = hti.screenshot(
        html_str=[html]*3,
        save_as="from_string_custom_size.png",
        size=test_sizes
    )

    for wanted_size, path in zip(test_sizes, paths):
        img = Image.open(path)
        assert wanted_size == img.size

@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_other_svg(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    paths = hti.screenshot(
        other_file='./examples/star.svg', save_as="star_svg.png"
    )

    img = Image.open(paths[0])
    pixels = img.load()

    assert (1920, 1080) == img.size  # default size

    # check colors at top left corner (assuming transparent background for the SVG)
    # for transparent PNG, the alpha channel will be 0
    assert pixels[0, 0][3] == 0  # check alpha channel for full transparency

@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_file(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    paths = hti.screenshot(
        html_file="./examples/blue_page.html",
        css_file="./examples/blue_background.css", # this CSS file is linked in blue_page.html
        save_as="from_file.png",
    )

    img = Image.open(paths[0])
    pixels = img.load()

    assert (1920, 1080) == img.size  # default size

    # check colors at top left corner
    assert pixels[0, 0][:3] == (0, 0, 255)  # blue + no transparency

@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_file_different_sizes(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    test_sizes = [
        (100, 100),
        (100, 1000),
        (100, 200),
    ]

    paths = hti.screenshot(
        html_file=["./examples/blue_page.html"]*3,
        save_as="from_file_custom_size.png",
        size=test_sizes
    )

    for wanted_size, path in zip(test_sizes, paths):
        img = Image.open(path)
        assert wanted_size == img.size


@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_html_str_with_css_file_only(browser):
    """Test html_str styled by a css_file only."""
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)
    html_content = "<h1>Background should be blue from file</h1>"
    css_file_path = "./examples/blue_background.css"

    paths = hti.screenshot(
        html_str=html_content,
        css_file=css_file_path,
        save_as="html_str_blue_bg_from_file.png"
    )

    img = Image.open(paths[0])
    pixels = img.load()
    assert (1920, 1080) == img.size

    # Check top-left corner for blue background
    assert pixels[0, 0][:3] == (0, 0, 255)  # blue

@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_html_str_with_css_str_and_css_file(browser):
    """Test html_str styled by both css_str (for a green block) and css_file (for blue body background)."""
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)
    
    # this CSS describes a green block, positioned absolutely,
    # using !important to ensure these styles apply
    css_string_content = """
    #green-block {
        background-color: rgb(0, 255, 0) !important; /* Green background */
        width: 150px !important;
        height: 100px !important;
        position: absolute !important;
        top: 75px !important;
        left: 75px !important;
    }
    """
    
    css_file_path = "./examples/blue_background.css"

    # div that will be styled by css_string_content
    html_content = '<div id="green-block"></div>'

    paths = hti.screenshot(
        html_str=html_content,
        css_str=css_string_content, # Styles #green-block
        css_file=css_file_path,     # Styles body background
        save_as="html_str_green_block_blue_bg.png",
        size=(500,400),
    )

    img = Image.open(paths[0])
    pixels = img.load()
    assert (500,400) == img.size

    # check body background color (blue)
    assert pixels[10, 10][:3] == (0, 0, 255)  # blue

    # check #green-block color (green from css_string_content)
    assert pixels[150, 125][:3] == (0, 255, 0)  # green

      
@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_html_str_with_multiple_css_files(browser):
    """Test html_str styled by multiple css_files using distinct background colors."""
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    # this CSS describes a red block, positioned absolutely,
    # using !important to ensure these styles apply
    temp_css_content = """
    #red-block {
        background-color: rgb(255, 0, 0) !important; /* red background */
        width: 200px !important;
        height: 150px !important;
        position: absolute !important; /* for predictable positioning */
        top: 50px !important;
        left: 50px !important;
    }
    """
    temp_css_filename = os.path.join(OUTPUT_PATH, "_temp_red_block.css")
    with open(temp_css_filename, "w") as f:
        f.write(temp_css_content)

    # the div that will be styled by _temp_red_block.css
    html_content = '<div id="red-block"></div>'

    css_file_paths = [
        "./examples/blue_background.css", # sets body { background: blue; }
        temp_css_filename                 # styles #red-block
    ]

    paths = hti.screenshot(
        html_str=html_content,
        css_file=css_file_paths,
        save_as="html_str_multi_css_blocks.png",
        size=(400,300),
    )

    # clean up temporary CSS file
    if os.path.exists(temp_css_filename):
        os.remove(temp_css_filename)

    img = Image.open(paths[0])
    pixels = img.load()
    assert (400,300) == img.size

    # check body background color (blue)
    assert pixels[10, 10][:3] == (0, 0, 255)  # blue

    # check #green-block color (red from _temp_red_block.css)
    assert pixels[150, 125][:3] == (255, 0, 0)  # red
    
@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_extend_size_param(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    assert hti._extend_size_param([(50, 50)], 1) \
        == [(50, 50)]

    assert hti._extend_size_param([(50, 50)], 3) \
        == [(50, 50), (50, 50), (50, 50)]

    assert hti._extend_size_param([(50, 50), (70, 60), (80, 90)], 5) \
        == [(50, 50), (70, 60), (80, 90), (80, 90), (80, 90)]

    assert hti._extend_size_param([], 3) \
        == [(1920, 1080), (1920, 1080), (1920, 1080)]

@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_extend_save_as_param(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    assert hti._extend_save_as_param(['a.png', 'b.png'], 2) == \
        ['a.png', 'b.png']

    assert hti._extend_save_as_param(['a.png', 'b.png'], 4) == \
        ['a.png', 'b_0.png', 'b_1.png', 'b_2.png']

    assert hti._extend_save_as_param(['a.png', 'b.png'], 0) == \
        ['a.png', 'b.png']

    assert hti._extend_save_as_param(['a.png', 'b.png', None, 65], 2) == \
        ['a.png', 'b.png']


def test_firefox_bidi_alias_maps_to_firefox_bidi_backend():
    hti = Html2Image(browser='firefox-bidi')
    assert type(hti.browser).__name__ == 'FirefoxBiDi'


def test_firefox_headless_alias_maps_to_firefox_headless_screenshot():
    hti = Html2Image(browser='firefox-headless')
    assert type(hti.browser).__name__ == 'FirefoxHeadlessScreenshot'


def test_bidi_port_forwarded():
    hti = Html2Image(browser='firefox-bidi', browser_bidi_port=9333)
    assert hti.browser._bidi_port == 9333


def test_bidi_port_not_forwarded_to_cdp_browser():
    hti = Html2Image(browser='chrome-cdp', browser_bidi_port=9333)
    assert not hasattr(hti.browser, '_bidi_port')


def test_edge_cdp_alias_maps_to_edge_cdp_backend():
    hti = Html2Image(browser='edge-cdp')
    assert type(hti.browser).__name__ == 'EdgeCDP'


def test_edge_cdp_port_forwarded():
    hti = Html2Image(browser='edge-cdp', browser_cdp_port=9444)
    assert hti.browser.cdp_port == 9444


def test_edge_headless_alias_maps_to_edge_headless_backend():
    hti = Html2Image(browser='edge-headless')
    assert type(hti.browser).__name__ == 'EdgeHeadless'


def test_edge_default_maps_to_cdp():
    hti = Html2Image(browser='edge')
    assert type(hti.browser).__name__ == 'EdgeCDP'


def test_firefox_alias_maps_to_firefox_bidi():
    hti = Html2Image(browser='firefox')
    assert type(hti.browser).__name__ == 'FirefoxBiDi'


def test_mozilla_firefox_alias_maps_to_firefox_bidi():
    hti = Html2Image(browser='mozilla-firefox')
    assert type(hti.browser).__name__ == 'FirefoxBiDi'


# ---------------------------------------------------------------------------
# full_page unit tests (no browser required)
# ---------------------------------------------------------------------------

def test_full_page_default_is_false():
    """full_page defaults to False — signature check without instantiating a browser."""
    import inspect
    from html2image.html2image import Html2Image as _H2I
    sig = inspect.signature(_H2I.screenshot)
    assert 'full_page' in sig.parameters
    assert sig.parameters['full_page'].default is False


@pytest.mark.parametrize("backend", ['chrome-headless', 'edge-headless', 'firefox-headless'])
def test_full_page_raises_on_headless_backends(backend):
    """full_page=True must raise NotImplementedError on CLI headless backends."""
    try:
        hti = Html2Image(browser=backend, output_path=OUTPUT_PATH, disable_logging=True)
    except FileNotFoundError:
        pytest.skip(f"'{backend}' executable not found on this machine")
    with pytest.raises(ValueError):
        hti.screenshot(
            html_str='<p>hi</p>',
            save_as='_full_page_headless_guard.png',
            size=(800, 600),
            full_page=True,
        )


def test_full_page_propagated_to_browser_screenshot(monkeypatch):
    """screenshot() must pass full_page down to browser.screenshot()."""
    received: dict = {}

    def _fake_screenshot(**kwargs):
        received.update(kwargs)

    hti = Html2Image(browser='chrome-cdp', output_path=OUTPUT_PATH, disable_logging=True)
    monkeypatch.setattr(hti.browser, 'screenshot', _fake_screenshot)

    hti.screenshot(
        url='https://example.com',
        save_as='_propagation_test.png',
        size=(800, 600),
        full_page=True,
    )
    assert received.get('full_page') is True


def test_full_page_false_preserves_the_historical_browser_call(monkeypatch):
    """Disabled page-fit must not add kwargs to custom browser calls."""
    received: dict = {}

    def _fake_screenshot(**kwargs):
        received.update(kwargs)

    hti = Html2Image(browser='chrome-cdp', output_path=OUTPUT_PATH, disable_logging=True)
    monkeypatch.setattr(hti.browser, 'screenshot', _fake_screenshot)

    hti.screenshot(
        url='https://example.com',
        save_as='_propagation_test_false.png',
        size=(800, 600),
    )
    assert 'full_page' not in received
    assert 'full_page_stability_timeout' not in received
    assert 'full_page_profile' not in received


def test_full_page_stability_timeout_propagated(monkeypatch):
    """screenshot() must pass full_page_stability_timeout down to browser.screenshot()."""
    received: dict = {}

    def _fake_screenshot(**kwargs):
        received.update(kwargs)

    hti = Html2Image(browser='chrome-cdp', output_path=OUTPUT_PATH, disable_logging=True)
    monkeypatch.setattr(hti.browser, 'screenshot', _fake_screenshot)

    hti.screenshot(
        url='https://example.com',
        save_as='_timeout_propagation_test.png',
        size=(800, 600),
        full_page=True,
        full_page_stability_timeout=7.5,
    )
    assert received.get('full_page_stability_timeout') == 7.5


@pytest.mark.parametrize("bad_value", [
    0,
    -1,
    -0.1,
    float('nan'),
    float('inf'),
    float('-inf'),
    "5",
    [],
    True,
])
def test_full_page_stability_timeout_validation(bad_value):
    """Invalid full_page_stability_timeout values must raise ValueError."""
    hti = Html2Image(browser='chrome-cdp', output_path=OUTPUT_PATH, disable_logging=True)
    with pytest.raises((ValueError, TypeError)):
        hti.screenshot(
            url='https://example.com',
            save_as='_timeout_validation_test.png',
            full_page=True,
            full_page_stability_timeout=bad_value,
        )


def test_full_page_stability_timeout_validation_screenshot_url():
    """screenshot_url() must validate full_page_stability_timeout at the public boundary."""
    hti = Html2Image(browser='chrome-cdp', output_path=OUTPUT_PATH, disable_logging=True)
    with pytest.raises(ValueError):
        hti.screenshot_url(
            url='https://example.com',
            output_file='_timeout_url_test.png',
            full_page=True,
            full_page_stability_timeout=-1,
        )


def test_full_page_stability_timeout_validation_screenshot_loaded_file(tmp_path):
    """screenshot_loaded_file() must validate full_page_stability_timeout at the public boundary."""
    hti = Html2Image(browser='chrome-cdp', output_path=OUTPUT_PATH, disable_logging=True)
    # Write a minimal HTML file into temp_path so the path join doesn't matter;
    # validation must fire before any file I/O.
    dummy = tmp_path / "dummy.html"
    dummy.write_text("<html></html>")
    hti.temp_path = str(tmp_path)
    with pytest.raises(ValueError):
        hti.screenshot_loaded_file(
            file='dummy.html',
            output_file='_timeout_loaded_test.png',
            full_page=True,
            full_page_stability_timeout=True,
        )


def test_full_page_stability_timeout_none_is_valid(monkeypatch):
    """None (default) must not raise and must be forwarded as-is."""
    received: dict = {}

    def _fake_screenshot(**kwargs):
        received.update(kwargs)

    hti = Html2Image(browser='chrome-cdp', output_path=OUTPUT_PATH, disable_logging=True)
    monkeypatch.setattr(hti.browser, 'screenshot', _fake_screenshot)

    hti.screenshot(
        url='https://example.com',
        save_as='_timeout_none_test.png',
        full_page=True,
        full_page_stability_timeout=None,
    )
    assert received.get('full_page_stability_timeout') is None


# ---------------------------------------------------------------------------
# full_page_profile tests
# ---------------------------------------------------------------------------

def test_full_page_profile_valid_values():
    for p in ('robust', 'balanced', 'fast'):
        Html2Image._validate_full_page_profile(p)  # doit passer sans exception


def test_full_page_profile_invalid_raises():
    with pytest.raises(ValueError, match="full_page_profile"):
        Html2Image._validate_full_page_profile('turbo')


def test_full_page_profile_default_is_robust():
    import inspect
    sig = inspect.signature(Html2Image.screenshot)
    assert sig.parameters['full_page_profile'].default == 'robust'


def test_screenshot_rejects_unknown_profile():
    hti = Html2Image(browser='chrome-cdp', output_path=OUTPUT_PATH, disable_logging=True)
    with pytest.raises(ValueError, match="full_page_profile"):
        hti.screenshot(
            html_str='<p>x</p>',
            save_as='_profile_validation_test.png',
            full_page=True,
            full_page_profile='turbo',
        )


def test_full_page_profile_propagated(monkeypatch):
    received = {}

    def _fake_screenshot(**kw):
        received.update(kw)

    hti = Html2Image(browser='chrome-cdp', output_path=OUTPUT_PATH, disable_logging=True)
    monkeypatch.setattr(hti.browser, 'screenshot', _fake_screenshot)
    hti.screenshot(
        url='https://example.com',
        save_as='_profile_propagated_test.png',
        full_page=True,
        full_page_profile='balanced',
    )
    assert received.get('full_page_profile') == 'balanced'


def test_full_page_profile_validation_screenshot_url():
    """screenshot_url() doit valider full_page_profile à la frontière publique."""
    hti = Html2Image(browser='chrome-cdp', output_path=OUTPUT_PATH, disable_logging=True)
    with pytest.raises(ValueError, match="full_page_profile"):
        hti.screenshot_url(
            url='https://example.com',
            output_file='_profile_url_test.png',
            full_page=True,
            full_page_profile='turbo',
        )


def test_full_page_profile_validation_screenshot_loaded_file(tmp_path):
    """screenshot_loaded_file() doit valider full_page_profile à la frontière publique."""
    hti = Html2Image(browser='chrome-cdp', output_path=OUTPUT_PATH, disable_logging=True)
    dummy = tmp_path / "dummy.html"
    dummy.write_text("<html></html>")
    hti.temp_path = str(tmp_path)
    with pytest.raises(ValueError, match="full_page_profile"):
        hti.screenshot_loaded_file(
            file='dummy.html',
            output_file='_profile_loaded_test.png',
            full_page=True,
            full_page_profile='turbo',
        )


def test_pyvips_import_error_message(monkeypatch):
    """ImportError raised when pyvips is absent must include the install hint."""
    import sys
    import html2image.browsers._page_fit_common as common

    # Simulate pyvips not being installed by setting its sys.modules entry to None
    monkeypatch.setitem(sys.modules, 'pyvips', None)

    with pytest.raises(ImportError, match='html2image\\[full-page\\]'):
        common.import_pyvips_for_stitching()


# ---------------------------------------------------------------------------
# full_page resource and fixed-element policy tests
# ---------------------------------------------------------------------------

def test_full_page_policy_defaults_are_public():
    import inspect

    signature = inspect.signature(Html2Image.screenshot)
    assert signature.parameters['full_page_fixed_elements'].default == 'auto'
    assert signature.parameters['full_page_max_pixels'].default == 100_000_000


@pytest.mark.parametrize(
    'mode', ['auto', 'preserve', 'first', 'last', 'hide']
)
def test_full_page_fixed_element_modes_are_valid(mode):
    Html2Image._validate_full_page_fixed_elements(mode)


@pytest.mark.parametrize('mode', ['repeat', '', None, 1, True])
def test_full_page_fixed_element_mode_validation(mode):
    with pytest.raises(ValueError, match='full_page_fixed_elements'):
        Html2Image._validate_full_page_fixed_elements(mode)


@pytest.mark.parametrize('value', [1, 100_000_000, None])
def test_full_page_max_pixels_valid_values(value):
    Html2Image._validate_full_page_max_pixels(value)


@pytest.mark.parametrize('value', [0, -1, 1.5, '1000', True])
def test_full_page_max_pixels_validation(value):
    with pytest.raises(ValueError, match='full_page_max_pixels'):
        Html2Image._validate_full_page_max_pixels(value)


def test_full_page_policy_options_are_propagated(monkeypatch):
    received = {}

    def _fake_screenshot(**kwargs):
        received.update(kwargs)

    hti = Html2Image(
        browser='chrome-cdp',
        output_path=OUTPUT_PATH,
        disable_logging=True,
    )
    monkeypatch.setattr(hti.browser, 'screenshot', _fake_screenshot)

    hti.screenshot(
        url='https://example.com',
        save_as='_full_page_policy_propagation.png',
        full_page=True,
        full_page_fixed_elements='last',
        full_page_max_pixels=None,
    )

    assert received['full_page_fixed_elements'] == 'last'
    assert received['full_page_max_pixels'] is None


def test_full_page_false_does_not_forward_new_policy_options(monkeypatch):
    received = {}

    def _fake_screenshot(**kwargs):
        received.update(kwargs)

    hti = Html2Image(
        browser='chrome-cdp',
        output_path=OUTPUT_PATH,
        disable_logging=True,
    )
    monkeypatch.setattr(hti.browser, 'screenshot', _fake_screenshot)

    hti.screenshot(
        url='https://example.com',
        save_as='_non_full_page_policy_propagation.png',
    )

    assert 'full_page_fixed_elements' not in received
    assert 'full_page_max_pixels' not in received


def test_temporary_html_is_removed_when_full_page_capture_fails(monkeypatch):
    hti = Html2Image(
        browser='chrome-cdp',
        output_path=OUTPUT_PATH,
        disable_logging=True,
    )

    def _raise(**kwargs):
        raise RuntimeError('capture failed')

    monkeypatch.setattr(hti.browser, 'screenshot', _raise)
    temporary_name = '_full_page_cleanup_failure.html'

    with pytest.raises(RuntimeError, match='capture failed'):
        hti.screenshot(
            html_str='<p>temporary</p>',
            save_as='_full_page_cleanup_failure.png',
            full_page=True,
        )

    assert not os.path.exists(os.path.join(hti.temp_path, temporary_name))
