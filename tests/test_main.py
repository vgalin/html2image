from html2image import Html2Image, BrowserError, CaptureTooLargeError
from html2image.browsers import chrome_cdp, chromium, firefox, firefox_bidi
from html2image.browsers import _page_fit_common as page_fit
from html2image.browsers.chrome_cdp import ChromeCDP
from pathlib import Path
from PIL import Image, ImageChops
from websocket import WebSocketTimeoutException

import json
import pytest
import os
import re
import socket

# The names of the browsers do not depend on the case.
TEST_BROWSERS = ["edGe", "cHrOme", "fIrEfOx"]
# Edge runs the code of Chrome, and "chrome-cdp" is another name for
# "chrome". The tests of what html2image does the same way in both, such as
# lists of pages, sizes and stylesheets, only use Chrome.
CHROME_ONLY = ["chrome"]
# Firefox has its own code.
CHROME_AND_FIREFOX = ["chrome", "firefox"]


def _make_hti(browser, output_path):
    """Html2Image for `browser`, or a skipped test if it is not installed."""
    try:
        return Html2Image(
            browser=browser, output_path=output_path, disable_logging=True
        )
    except FileNotFoundError:
        pytest.skip(f"'{browser}' executable not found on this machine")


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

BACKENDS = {
    "chrome": "ChromeCDP",
    "chrome-cdp": "ChromeCDP",
    "chrome-headless": "ChromeHeadless",
    "edge": "EdgeCDP",
    "edge-cdp": "EdgeCDP",
    "edge-headless": "EdgeHeadless",
    "firefox": "FirefoxBiDi",
    "firefox-bidi": "FirefoxBiDi",
    "mozilla-firefox": "FirefoxBiDi",
    "firefox-headless": "FirefoxHeadlessScreenshot",
}


def test_browser_names_map_to_their_backends():
    for name, backend in BACKENDS.items():
        hti = Html2Image(browser=name)
        assert type(hti.browser).__name__ == backend, name


def test_cdp_port_forwarded():
    hti = Html2Image(browser='chrome-cdp', browser_cdp_port=9555)
    assert hti.browser.cdp_port == 9555


def test_default_chrome_cdp_port_is_automatic():
    hti = Html2Image(browser='chrome')
    assert hti.browser.cdp_port is None


# The tests below replace subprocess functions only after creating
# Html2Image: on macOS, finding the browser runs it with subprocess.
class FakeProcess:
    def poll(self):
        return 0


@pytest.mark.parametrize("browser", ["chrome", "edge"])
@pytest.mark.parametrize("allowed", [False, True])
def test_allow_scripts_to_read_files_flag(monkeypatch, browser, allowed):
    commands = []

    def fake_popen(command, **kwargs):
        commands.append(command)
        return FakeProcess()

    hti = Html2Image(browser=browser, allow_scripts_to_read_files=allowed)
    monkeypatch.setattr(chrome_cdp.subprocess, "Popen", fake_popen)
    hti.browser._start_chrome()
    hti.browser.__exit__()

    assert ("--allow-file-access-from-files" in commands[0]) is allowed


@pytest.mark.parametrize("browser", ["chrome", "edge"])
@pytest.mark.parametrize(
    "custom_flags, on_windows, elsewhere",
    [
        (None, 1, 0),
        (["--virtual-time-budget=5000"], 1, 0),
        (["--disable-skia-graphite"], 1, 1),
        (["--enable-skia-graphite"], 0, 0),
    ],
)
def test_skia_graphite_disabled_on_windows(
    monkeypatch, browser, custom_flags, on_windows, elsewhere
):
    commands = []

    def fake_popen(command, **kwargs):
        commands.append(command)
        return FakeProcess()

    hti = Html2Image(browser=browser, custom_flags=custom_flags)
    monkeypatch.setattr(chrome_cdp.subprocess, "Popen", fake_popen)
    hti.browser._start_chrome()
    hti.browser.__exit__()

    expected = on_windows if os.name == "nt" else elsewhere
    assert commands[0].count("--disable-skia-graphite") == expected


@pytest.mark.parametrize("browser", ["chrome-headless", "edge-headless"])
@pytest.mark.parametrize("allowed", [False, True])
def test_allow_scripts_to_read_files_flag_cli(
    monkeypatch, tmp_path, browser, allowed
):
    commands = []
    hti = Html2Image(browser=browser, allow_scripts_to_read_files=allowed)
    monkeypatch.setattr(
        chromium.subprocess, "run",
        lambda command, **kwargs: commands.append(command),
    )
    hti.browser.screenshot("about:blank", str(tmp_path))

    assert ("--allow-file-access-from-files" in commands[0]) is allowed
    assert "--hide-scrollbars" in commands[0]  # default flags are kept


def _read_profile_prefs(command):
    profile_dir = command[command.index("--profile") + 1]
    return Path(profile_dir, "user.js").read_text(encoding="utf-8")


def _strict_origin_pref(allowed):
    value = "false" if allowed else "true"
    return f'user_pref("security.fileuri.strict_origin_policy", {value});'


@pytest.mark.parametrize("allowed", [False, True])
def test_allow_scripts_to_read_files_pref_firefox(monkeypatch, allowed):
    prefs = []

    def fake_popen(command, **kwargs):
        prefs.append(_read_profile_prefs(command))
        return FakeProcess()

    hti = Html2Image(browser="firefox", allow_scripts_to_read_files=allowed)
    monkeypatch.setattr(firefox_bidi.subprocess, "Popen", fake_popen)
    hti.browser._start_firefox()
    hti.browser.__exit__()

    assert _strict_origin_pref(allowed) in prefs[0]


@pytest.mark.parametrize("allowed", [False, True])
def test_allow_scripts_to_read_files_pref_firefox_headless(
    monkeypatch, tmp_path, allowed
):
    prefs = []

    def fake_run(command, **kwargs):
        prefs.append(_read_profile_prefs(command))
        (tmp_path / "screenshot.png").touch()

    hti = Html2Image(
        browser="firefox-headless", allow_scripts_to_read_files=allowed
    )
    monkeypatch.setattr(firefox.subprocess, "run", fake_run)
    hti.browser.screenshot("about:blank", str(tmp_path))

    assert _strict_origin_pref(allowed) in prefs[0]


# The page reads the file with a synchronous XHR because firefox-headless
# takes its screenshot as soon as the page has loaded: the response of an
# asynchronous fetch would often arrive too late.
READ_FILE_HTML = """
<script>
    let color = "#ff0000";
    try {
        const request = new XMLHttpRequest();
        request.open("GET", "secret.txt", false);
        request.send();
        if (request.responseText === "secret") color = "#00ff00";
    } catch (error) {}
    document.documentElement.style.background = color;
</script>
"""


@pytest.mark.parametrize("browser", [
    "chrome", "edge", "firefox",
    "chrome-headless", "edge-headless", "firefox-headless",
])
@pytest.mark.parametrize("allowed", [False, True])
def test_allow_scripts_to_read_files_screenshot(
    tmp_path, browser, allowed, output_path
):
    try:
        hti = Html2Image(
            browser=browser,
            output_path=output_path,
            temp_path=str(tmp_path / "temp"),
            disable_logging=True,
            allow_scripts_to_read_files=allowed,
        )
    except FileNotFoundError:
        pytest.skip(f"'{browser}' executable not found on this machine")

    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("secret")
    hti.load_file(str(secret_file))

    paths = hti.screenshot(
        html_str=READ_FILE_HTML,
        save_as=f"read_files_{browser}_{allowed}.png",
        size=(320, 240),
    )

    expected = (0, 255, 0) if allowed else (255, 0, 0)
    assert Image.open(paths[0]).convert("RGB").getpixel((10, 10)) == expected


@pytest.mark.parametrize("add_doctype", [False, True])
def test_prepare_html_string_doctype(add_doctype):
    html = Html2Image._prepare_html_string("Hello", "", add_doctype)

    assert html.startswith("<!DOCTYPE html>\n<html>") is add_doctype
    assert html.startswith("<html>") is not add_doctype


COMPAT_MODE_HTML = """
<script>
    const standard = document.compatMode === "CSS1Compat";
    document.documentElement.style.background = standard ? "#00ff00" : "#ff0000";
</script>
"""


# The doctype is added by html2image, before the page reaches the browser:
# one browser of each engine is enough to see how the page is rendered.
@pytest.mark.parametrize("browser", ["chrome", "firefox"])
@pytest.mark.parametrize("add_doctype", [False, True])
def test_add_doctype_screenshot(tmp_path, browser, add_doctype, output_path):
    try:
        hti = Html2Image(
            browser=browser,
            output_path=output_path,
            temp_path=str(tmp_path / "temp"),
            disable_logging=True,
            add_doctype=add_doctype,
        )
    except FileNotFoundError:
        pytest.skip(f"'{browser}' executable not found on this machine")

    paths = hti.screenshot(
        html_str=COMPAT_MODE_HTML,
        save_as=f"doctype_{browser}_{add_doctype}.png",
        size=(320, 240),
    )

    expected = (0, 255, 0) if add_doctype else (255, 0, 0)
    assert Image.open(paths[0]).convert("RGB").getpixel((10, 10)) == expected


@pytest.mark.parametrize("browser", CHROME_ONLY)
def test_issue177_exact_size_contract(browser, output_path):
    hti = Html2Image(
        browser=browser, output_path=output_path, disable_logging=True
    )
    paths = hti.screenshot(
        html_str='<body style="margin:0;background:green"></body>',
        save_as=f'issue177_size_{browser}.png',
        size=(800, 480),
    )
    img = Image.open(paths[0])
    assert img.size == (800, 480)


@pytest.mark.parametrize("browser", CHROME_ONLY)
def test_issue177_no_bottom_strip_100vh(browser, output_path):
    hti = Html2Image(
        browser=browser, output_path=output_path, disable_logging=True
    )
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


@pytest.mark.parametrize("browser", CHROME_ONLY)
def test_issue177_svg_transparent_background(browser, output_path):
    hti = Html2Image(
        browser=browser, output_path=output_path, disable_logging=True
    )
    paths = hti.screenshot(
        other_file='./examples/star.svg',
        save_as=f'issue177_svg_alpha_{browser}.png',
        size=(500, 500),
    )

    img = Image.open(paths[0]).convert("RGBA")
    assert img.size == (500, 500)
    assert img.getpixel((0, 0))[3] == 0


@pytest.mark.parametrize("browser", CHROME_AND_FIREFOX)
def test_issue177_jpg_output_format(browser, output_path):
    hti = _make_hti(browser, output_path)
    paths = hti.screenshot(
        html_str='<body style="margin:0;background:#00aa00"></body>',
        save_as=f'issue177_jpg_{browser}.jpg',
        size=(640, 360),
    )

    img = Image.open(paths[0])
    assert img.size == (640, 360)
    assert img.format == "JPEG"


RED, GREEN, BLUE = (255, 0, 0), (0, 255, 0), (0, 0, 255)


def _page_of_color(color):
    return '<body style="margin:0;background:rgb%s"></body>' % (color,)


@pytest.mark.parametrize("browser", ["chrome", "edge", "firefox"])
def test_screenshot_url(output_path, serve, browser):
    hti = _make_hti(browser, output_path)

    [path] = hti.screenshot(url=serve(_page_of_color(BLUE)), save_as="url.png")

    img = Image.open(path).convert("RGB")
    assert img.size == (1920, 1080)  # default size
    assert img.getpixel((10, 10)) == BLUE


@pytest.mark.parametrize("browser", CHROME_ONLY)
def test_screenshot_urls_with_sizes_and_names(output_path, serve, browser):
    hti = Html2Image(
        browser=browser, output_path=output_path, disable_logging=True
    )
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


@pytest.mark.parametrize("browser", TEST_BROWSERS)
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

@pytest.mark.parametrize("browser", CHROME_ONLY)
def test_screenshot_string_different_sizes(browser, output_path):
    hti = Html2Image(
        browser=browser, output_path=output_path, disable_logging=True
    )

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

@pytest.mark.parametrize("browser", CHROME_AND_FIREFOX)
def test_screenshot_file(browser, output_path):
    hti = _make_hti(browser, output_path)

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

@pytest.mark.parametrize("browser", CHROME_ONLY)
def test_screenshot_file_different_sizes(browser, output_path):
    hti = Html2Image(
        browser=browser, output_path=output_path, disable_logging=True
    )

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


@pytest.mark.parametrize("browser", CHROME_ONLY)
def test_screenshot_html_str_with_css_str_and_css_file(browser, output_path):
    """Test html_str styled by both css_str (for a green block) and css_file (for blue body background)."""
    hti = Html2Image(
        browser=browser, output_path=output_path, disable_logging=True
    )
    
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

      
@pytest.mark.parametrize("browser", CHROME_ONLY)
def test_screenshot_html_str_with_multiple_css_files(browser, output_path):
    """Test html_str styled by multiple css_files using distinct background colors."""
    hti = Html2Image(
        browser=browser, output_path=output_path, disable_logging=True
    )

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
    temp_css_filename = os.path.join(output_path, "_temp_red_block.css")
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
    
def test_extend_size_param(output_path):
    hti = Html2Image(output_path=output_path, disable_logging=True)

    assert hti._extend_size_param([(50, 50)], 1) \
        == [(50, 50)]

    assert hti._extend_size_param([(50, 50)], 3) \
        == [(50, 50), (50, 50), (50, 50)]

    assert hti._extend_size_param([(50, 50), (70, 60), (80, 90)], 5) \
        == [(50, 50), (70, 60), (80, 90), (80, 90), (80, 90)]

    assert hti._extend_size_param([], 3) \
        == [(1920, 1080), (1920, 1080), (1920, 1080)]

def test_extend_save_as_param(output_path):
    hti = Html2Image(output_path=output_path, disable_logging=True)

    assert hti._extend_save_as_param(['a.png', 'b.png'], 2) == \
        ['a.png', 'b.png']

    assert hti._extend_save_as_param(['a.png', 'b.png'], 4) == \
        ['a.png', 'b_0.png', 'b_1.png', 'b_2.png']

    assert hti._extend_save_as_param(['a.png', 'b.png'], 0) == \
        ['a.png', 'b.png']

    assert hti._extend_save_as_param(['a.png', 'b.png', None, 65], 2) == \
        ['a.png', 'b.png']


def test_bidi_port_forwarded():
    hti = Html2Image(browser='firefox-bidi', browser_bidi_port=9333)
    assert hti.browser._bidi_port == 9333


def test_bidi_port_not_forwarded_to_cdp_browser():
    hti = Html2Image(browser='chrome-cdp', browser_bidi_port=9333)
    assert not hasattr(hti.browser, '_bidi_port')


def test_edge_cdp_port_forwarded():
    hti = Html2Image(browser='edge-cdp', browser_cdp_port=9444)
    assert hti.browser.cdp_port == 9444


# ---------------------------------------------------------------------------
# full_page unit tests (no browser required)
# ---------------------------------------------------------------------------

def test_full_page_default_is_false():
    """full_page defaults to False, checked without starting a browser."""
    import inspect
    from html2image.html2image import Html2Image as _H2I
    sig = inspect.signature(_H2I.screenshot)
    assert 'full_page' in sig.parameters
    assert sig.parameters['full_page'].default is False


@pytest.mark.parametrize("backend", ['chrome-headless', 'edge-headless', 'firefox-headless'])
def test_full_page_raises_on_headless_backends(backend, output_path):
    """full_page=True must raise ValueError on CLI headless backends."""
    try:
        hti = Html2Image(
            browser=backend, output_path=output_path, disable_logging=True
        )
    except FileNotFoundError:
        pytest.skip(f"'{backend}' executable not found on this machine")
    with pytest.raises(ValueError, match='"firefox-headless"'):
        hti.screenshot(
            html_str='<p>hi</p>',
            save_as='_full_page_headless_guard.png',
            size=(800, 600),
            full_page=True,
        )


def _full_page_options(received):
    return [
        {key: value for key, value in options.items()
         if key.startswith('full_page')}
        for options in received
    ]


def test_full_page_propagated_to_browser_screenshot(monkeypatch, output_path):
    """screenshot() must pass the full page options, given or not, down to
    browser.screenshot()."""
    received = []
    hti = Html2Image(
        browser='chrome-cdp', output_path=output_path, disable_logging=True
    )
    monkeypatch.setattr(
        hti.browser, 'screenshot', lambda **kwargs: received.append(kwargs)
    )

    hti.screenshot(
        url='http://127.0.0.1:1/', save_as='default.png', full_page=True
    )
    hti.screenshot(
        url='http://127.0.0.1:1/',
        save_as='options.png',
        full_page=True,
        full_page_stability_timeout=7.5,
        full_page_profile='robust',
        full_page_fixed_elements='last',
        full_page_max_pixels=None,
    )

    assert _full_page_options(received) == [
        {
            'full_page': True,
            'full_page_stability_timeout': None,
            'full_page_profile': 'balanced',
            'full_page_fixed_elements': 'auto',
            'full_page_max_pixels': 100_000_000,
        },
        {
            'full_page': True,
            'full_page_stability_timeout': 7.5,
            'full_page_profile': 'robust',
            'full_page_fixed_elements': 'last',
            'full_page_max_pixels': None,
        },
    ]


def test_full_page_false_preserves_the_historical_browser_call(
    monkeypatch, output_path
):
    """Disabled page-fit must not add kwargs to custom browser calls."""
    received = []
    hti = Html2Image(
        browser='chrome-cdp', output_path=output_path, disable_logging=True
    )
    monkeypatch.setattr(
        hti.browser, 'screenshot', lambda **kwargs: received.append(kwargs)
    )

    hti.screenshot(
        url='http://127.0.0.1:1/',
        save_as='_propagation_test_false.png',
        size=(800, 600),
    )
    assert _full_page_options(received) == [{}]


def test_full_page_stability_timeout_validation(output_path):
    """screenshot() checks full_page_stability_timeout. The values it
    refuses are tested in test_page_fit_common.py."""
    hti = Html2Image(
        browser='chrome-cdp', output_path=output_path, disable_logging=True
    )
    with pytest.raises(ValueError, match="full_page_stability_timeout"):
        hti.screenshot(
            url='http://127.0.0.1:1/',
            save_as='_timeout_validation_test.png',
            full_page=True,
            full_page_stability_timeout=0,
        )


@pytest.mark.parametrize("options", [
    {"save_as": ["first.png", "second.webp"]},
    {"save_as": ["first.png", "second.png"], "size": [(400, 300), (400.0, 300)]},
])
def test_full_page_checks_names_and_sizes_before_loading(
    monkeypatch, options, output_path
):
    """A name or a size refused by full_page is refused before any page is
    loaded, so that no image of the batch is saved."""
    loaded = []
    hti = Html2Image(
        browser='chrome-cdp', output_path=output_path, disable_logging=True
    )
    monkeypatch.setattr(
        hti.browser, 'screenshot', lambda **kwargs: loaded.append(kwargs)
    )

    with pytest.raises(ValueError):
        hti.screenshot(html_str=['first', 'second'], full_page=True, **options)
    assert loaded == []


# ---------------------------------------------------------------------------
# full_page_profile tests
# ---------------------------------------------------------------------------

def test_full_page_profile_valid_values():
    for p in ('robust', 'balanced', 'fast'):
        page_fit.validate_full_page_profile(p)  # doit passer sans exception


def test_full_page_profile_depends_on_the_source(
    monkeypatch, tmp_path, output_path
):
    page = tmp_path / '_profile_file_test.html'
    page.write_text('<p>x</p>')
    received = []
    hti = Html2Image(
        browser='chrome-cdp', output_path=output_path, disable_logging=True
    )
    monkeypatch.setattr(
        hti.browser, 'screenshot', lambda **kw: received.append(kw)
    )
    hti.screenshot(
        html_str='<p>x</p>',
        html_file=str(page),
        url='https://example.com',
        save_as=['_profile_str.png', '_profile_file.png', '_profile_url.png'],
        full_page=True,
    )
    profiles = [kw['full_page_profile'] for kw in received]
    assert profiles == ['fast', 'fast', 'balanced']


def test_screenshot_rejects_unknown_profile(output_path):
    hti = Html2Image(
        browser='chrome-cdp', output_path=output_path, disable_logging=True
    )
    with pytest.raises(ValueError, match="full_page_profile"):
        hti.screenshot(
            html_str='<p>x</p>',
            save_as='_profile_validation_test.png',
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
    page_fit.validate_fixed_element_mode(mode)


@pytest.mark.parametrize('mode', ['repeat', '', None, 1, True])
def test_full_page_fixed_element_mode_validation(mode):
    with pytest.raises(ValueError, match='full_page_fixed_elements'):
        page_fit.validate_fixed_element_mode(mode)


@pytest.mark.parametrize('value', [1, 100_000_000, None])
def test_full_page_max_pixels_valid_values(value):
    page_fit.validate_max_pixels(value)


def test_full_page_rejects_selector(tmp_path):
    hti = Html2Image(browser="chrome", output_path=str(tmp_path))

    with pytest.raises(ValueError, match="selector and full_page"):
        hti.screenshot(html_str="Hello", selector="p", full_page=True)

    assert not list(tmp_path.iterdir())


def test_too_large_full_page_does_not_stop_the_other_pages(
    monkeypatch, tmp_path
):
    hti = Html2Image(browser="chrome", output_path=str(tmp_path))

    def screenshot(output_file, **kwargs):
        if output_file == "tall.png":
            raise CaptureTooLargeError("Too large")
        (tmp_path / output_file).write_bytes(b"image")

    monkeypatch.setattr(hti.browser, "screenshot", screenshot)

    with pytest.raises(CaptureTooLargeError, match="tall.png") as error:
        hti.screenshot(
            html_str=["short", "tall", "short"],
            save_as=["first.png", "tall.png", "last.png"],
            full_page=True,
        )

    assert error.value.paths == [
        os.path.join(str(tmp_path), name) for name in ("first.png", "last.png")
    ]
    assert error.value.too_large == [(None, "tall.png")]


def test_too_large_full_page_gives_the_reason_of_each_image(
    monkeypatch, tmp_path
):
    hti = Html2Image(browser="chrome", output_path=str(tmp_path))

    def screenshot(output_file, **kwargs):
        if output_file == "big.png":
            page_fit.enforce_pixel_budget(10_000, 20_000, 100_000_000)
        page_fit.enforce_format_limit(400, 66_000, "jpeg")

    monkeypatch.setattr(hti.browser, "screenshot", screenshot)

    with pytest.raises(CaptureTooLargeError) as error:
        hti.screenshot(
            html_str=["big", "high"],
            save_as=["big.png", "high.jpg"],
            full_page=True,
        )

    assert str(error.value) == (
        "Too large to be captured: big.png.\n"
        "The image would have had more than 100,000,000 pixels, the limit "
        "set by full_page_max_pixels. Raise the limit, or set it to None to "
        "remove it.\n"
        "Too large to be captured: high.jpg.\n"
        "A JPEG image cannot be wider or higher than 65,500 pixels. Save it "
        "as a PNG image instead."
    )


def test_too_high_jpeg_without_a_pixel_limit(monkeypatch, tmp_path):
    hti = Html2Image(browser="chrome", output_path=str(tmp_path))
    monkeypatch.setattr(
        hti.browser, "screenshot",
        lambda **kwargs: page_fit.enforce_format_limit(400, 66_000, "jpeg"),
    )

    with pytest.raises(CaptureTooLargeError, match="A JPEG image cannot"):
        hti.screenshot(
            html_str="high",
            save_as="high.jpg",
            full_page=True,
            full_page_max_pixels=None,
        )


@pytest.mark.parametrize("save_as", ["../escaped.png", os.path.abspath("escaped.png")])
def test_screenshot_save_as_path_writes_nothing(
    tmp_path, save_as, output_path
):
    temp_path = tmp_path / "temp"
    hti = Html2Image(temp_path=str(temp_path), output_path=output_path)

    with pytest.raises(ValueError):
        hti.screenshot(html_str="Hello", save_as=save_as)

    assert not (tmp_path / "escaped.html").exists()
    assert not os.path.exists("escaped.html")


def test_load_str_rejects_path(tmp_path, output_path):
    temp_path = tmp_path / "temp"
    hti = Html2Image(temp_path=str(temp_path), output_path=output_path)

    with pytest.raises(ValueError):
        hti.load_str("Hello", as_filename="../escaped.html")

    assert not (tmp_path / "escaped.html").exists()


def test_load_file_rejects_path(tmp_path, output_path):
    temp_path = tmp_path / "temp"
    hti = Html2Image(temp_path=str(temp_path), output_path=output_path)

    with pytest.raises(ValueError):
        hti.load_file("./examples/blue_page.html", as_filename="../escaped.html")

    assert not (tmp_path / "escaped.html").exists()


@pytest.mark.parametrize(
    "browser", ["chrome-headless", "edge-headless", "firefox-headless"]
)
@pytest.mark.parametrize("prefix", ["", " ", "\t"])
def test_cli_backends_reject_input_read_as_flag(
    tmp_path, browser, prefix, output_path
):
    hti = Html2Image(
        browser=browser, output_path=output_path, disable_logging=True
    )
    injected_output = tmp_path / "injected.png"

    # Chromium strips the whitespace around its arguments
    with pytest.raises(ValueError):
        hti.screenshot(
            url=f"{prefix}--screenshot={injected_output}",
            save_as=f"flag_as_url_{browser}.png",
        )

    assert not injected_output.exists()


def test_chrome_instances_use_different_cdp_ports(output_path):
    first = Html2Image(
        browser="chrome", output_path=output_path, disable_logging=True
    )
    second = Html2Image(
        browser="chrome", output_path=output_path, disable_logging=True
    )

    with first, second:
        assert first.browser._current_port != second.browser._current_port

        for hti, color, rgb in [
            (first, "red", (255, 0, 0)),
            (second, "blue", (0, 0, 255)),
            (first, "red", (255, 0, 0)),
        ]:
            paths = hti.screenshot(
                html_str=f'<body style="margin:0;background:{color}"></body>',
                save_as=f"cdp_two_instances_{color}.png",
                size=(320, 240),
            )
            img = Image.open(paths[0]).convert("RGB")
            assert img.getpixel((0, 0)) == rgb


def test_chrome_cdp_virtual_time_budget(output_path):
    hti = Html2Image(
        browser="chrome",
        output_path=output_path,
        disable_logging=True,
        custom_flags=["--virtual-time-budget=5000", "--hide-scrollbars"],
    )
    html = (
        '<body style="margin:0;background:red"><script>'
        "setTimeout(() => { document.body.style.background = 'blue' }, 1500)"
        "</script></body>"
    )

    with hti:
        for i in range(2):
            paths = hti.screenshot(
                html_str=html,
                save_as=f"cdp_virtual_time_{i}.png",
                size=(320, 240),
            )
            img = Image.open(paths[0]).convert("RGB")
            assert img.getpixel((0, 0)) == (0, 0, 255)


# With the attribute that holds the profile folder of the browser.
@pytest.mark.parametrize("browser, profile", [
    ("edge", "_user_data_dir"), ("firefox", "_profile_dir"),
], ids=["edge", "firefox"])
def test_context_manager_keeps_one_browser(browser, profile, output_path):
    hti = _make_hti(browser, output_path)
    sizes = [(400, 300), (640, 480), (320, 240)]

    with hti:
        profile_dir = getattr(hti.browser, profile)
        port = hti.browser._current_port

        for i, size in enumerate(sizes):
            [path] = hti.screenshot(
                html_str='<body style="margin:0;background:red"></body>',
                save_as=f"same_browser_{i}.png",
                size=size,
            )
            assert Image.open(path).size == size
            assert getattr(hti.browser, profile) == profile_dir

    # The browser is closed: nothing listens on its port anymore.
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=2).close()


class FakeWebSocket:
    """Replays CDP messages, then times out like an idle connection."""

    def __init__(self, messages):
        self.messages = [json.dumps(message) for message in messages]

    def settimeout(self, timeout):
        pass

    def recv(self):
        if not self.messages:
            raise WebSocketTimeoutException()
        return self.messages.pop(0)


PREVIOUS_PAGE_EVENTS = [
    {"method": "Page.loadEventFired", "params": {}},
    {"method": "Page.frameStoppedLoading", "params": {"frameId": "main"}},
    {
        "method": "Page.lifecycleEvent",
        "params": {"frameId": "main", "loaderId": "previous", "name": "load"},
    },
]
NAVIGATION_RESULT = {"id": 1, "result": {"frameId": "main", "loaderId": "requested"}}


def test_cdp_navigation_ignores_load_events_of_previous_page():
    browser = ChromeCDP()
    browser._ws = FakeWebSocket(PREVIOUS_PAGE_EVENTS + [NAVIGATION_RESULT])

    with pytest.raises(TimeoutError):
        browser._wait_for_navigation_complete(1, timeout=1)


def test_cdp_navigation_completes_on_load_event_of_requested_page():
    browser = ChromeCDP()
    browser._ws = FakeWebSocket(PREVIOUS_PAGE_EVENTS + [
        NAVIGATION_RESULT,
        {
            "method": "Page.lifecycleEvent",
            "params": {"frameId": "main", "loaderId": "requested", "name": "load"},
        },
    ])

    assert browser._wait_for_navigation_complete(1, timeout=1) == NAVIGATION_RESULT


def test_cdp_navigation_within_same_document_completes():
    browser = ChromeCDP()
    navigation_result = {"id": 1, "result": {"frameId": "main"}}
    browser._ws = FakeWebSocket([navigation_result])

    assert browser._wait_for_navigation_complete(1, timeout=1) == navigation_result


def test_chrome_cdp_screenshot_url_then_its_anchor(output_path):
    hti = Html2Image(
        browser="chrome", output_path=output_path, disable_logging=True
    )
    hti.load_file("./examples/blue_page.html", as_filename="anchor_page.html")
    page = os.path.join(hti.temp_path, "anchor_page.html")

    with hti:
        user_data_dir = hti.browser._user_data_dir

        for anchor in ["", "#first", "#second"]:
            paths = hti.screenshot(
                url=Path(page).as_uri() + anchor,
                save_as="cdp_anchor.png",
                size=(320, 240),
            )
            img = Image.open(paths[0])
            assert img.size == (320, 240)

        # no failed screenshot restarted the browser
        assert hti.browser._user_data_dir == user_data_dir

    hti._remove_temp_file("anchor_page.html")


def test_cdp_lost_page_raises_immediately():
    browser = ChromeCDP()
    browser._ws = FakeWebSocket([
        {"method": "Inspector.detached", "params": {"reason": "Render process gone."}},
        {"id": 1, "result": {}},
    ])

    with pytest.raises(BrowserError, match="Render process gone"):
        browser._wait_for_result(1, timeout=1)


def test_cdp_session_recovers_after_navigation_timeout(
    monkeypatch, unresponsive_url, output_path
):
    hti = Html2Image(
        browser="chrome", output_path=output_path, disable_logging=True
    )

    wait_for_navigation = hti.browser._wait_for_navigation_complete
    monkeypatch.setattr(
        hti.browser,
        "_wait_for_navigation_complete",
        lambda nav_id: wait_for_navigation(nav_id, timeout=2),
    )

    with hti:
        browser_pid = hti.browser._browser_pid
        with pytest.raises(TimeoutError):
            hti.screenshot(url=unresponsive_url, save_as="cdp_timeout.png")

        # the browser was restarted, as the page may still be loading
        assert hti.browser._browser_pid != browser_pid
        paths = hti.screenshot(
            html_str='<body style="margin:0;background:blue"></body>',
            save_as="cdp_after_timeout.png",
            size=(320, 240),
        )

    img = Image.open(paths[0]).convert("RGB")
    assert img.getpixel((0, 0)) == (0, 0, 255)


def _pdf_options(paper_size="A4", landscape=None, margin=None, scale=1):
    return Html2Image._prepare_pdf_options(
        paper_size, landscape, margin, True, scale
    )


@pytest.mark.parametrize("paper_size", ["B9", "", ("1cm",), ("0", "1cm")])
def test_pdf_rejects_invalid_paper_size(paper_size):
    with pytest.raises(ValueError):
        _pdf_options(paper_size=paper_size)


@pytest.mark.parametrize("length", ["1em", "10%", "cm", "1 cm", "-1cm", "1,5cm", "1cm2"])
def test_pdf_rejects_invalid_unit(length):
    with pytest.raises(ValueError):
        _pdf_options(margin=length)


@pytest.mark.parametrize("length", [1, 2.5, "1", "0.5"])
def test_pdf_rejects_number_without_unit(length):
    with pytest.raises(ValueError):
        _pdf_options(paper_size=(length, "10cm"))


@pytest.mark.parametrize("length", [0, 0.0, "0", "0.0"])
def test_pdf_accepts_zero_without_unit(length):
    assert _pdf_options(margin=length)["margin"] == (0, 0, 0, 0)


@pytest.mark.parametrize(
    "length", ["25.4mm", "2.54cm", "101.6Q", "101.6q", "1in", "1IN", "72pt", "6pc", "96px"]
)
def test_pdf_css_units(length):
    assert _pdf_options(margin=length)["margin"] == pytest.approx((1, 1, 1, 1))


@pytest.mark.parametrize("margin, expected", [
    ("1in", (1, 1, 1, 1)),
    ("1in 2in", (1, 2, 1, 2)),
    ("1in 2in 3in", (1, 2, 3, 2)),
    ("1in 2in 3in 4in", (1, 2, 3, 4)),
])
def test_pdf_margin_shorthand(margin, expected):
    assert _pdf_options(margin=margin)["margin"] == expected


@pytest.mark.parametrize("margin", ["", "1in 2in 3in 4in 5in"])
def test_pdf_rejects_margin_length_count(margin):
    with pytest.raises(ValueError):
        _pdf_options(margin=margin)


@pytest.mark.parametrize("paper_size, landscape, margin", [
    ("A4", None, "15cm"),
    # Left and right margins that take the whole 8.5in width.
    ("Letter", None, "1in 4.25in"),
    # Top and bottom margins of 11cm fit on A4 upright (29.7cm high),
    # but not sideways (21cm high).
    ("A4", True, "11cm 0"),
])
def test_pdf_rejects_margin_larger_than_paper(paper_size, landscape, margin):
    with pytest.raises(ValueError, match="no room"):
        _pdf_options(paper_size=paper_size, landscape=landscape, margin=margin)


def test_pdf_accepts_margin_close_to_paper_size():
    # 2 x 10cm on A4, which is 21cm wide.
    assert _pdf_options(margin="10cm")["margin"] == pytest.approx((10 / 2.54,) * 4)


@pytest.mark.parametrize("paper_size, margin", [
    ("A4", 1 / 2.54),
    (("10in", "5in"), 1 / 2.54),
    ("slide", 0),
    ("SLIDE", 0),
])
def test_pdf_default_margin(paper_size, margin):
    assert _pdf_options(paper_size=paper_size)["margin"] == (margin,) * 4


A4 = (210 / 25.4, 297 / 25.4)
SLIDE = (1280 / 96, 720 / 96)


@pytest.mark.parametrize("paper_size, landscape, expected", [
    ("A4", None, A4),
    ("a4", False, A4),
    ("A4", True, A4[::-1]),
    ("letter", None, (8.5, 11)),
    ("Letter", True, (11, 8.5)),
    ("slide", None, SLIDE),
    ("slide", True, SLIDE),
    ("slide", False, SLIDE[::-1]),
    (("17in", "11in"), None, (17, 11)),
    # The dimensions are already in landscape: they are not swapped again.
    (("17in", "11in"), True, (17, 11)),
    (("17in", "11in"), False, (11, 17)),
    (("11in", "17in"), True, (17, 11)),
])
def test_pdf_paper_dimensions(paper_size, landscape, expected):
    options = _pdf_options(paper_size=paper_size, landscape=landscape)
    assert (options["width"], options["height"]) == pytest.approx(expected)


@pytest.mark.parametrize("scale", [0.05, 2.5])
def test_pdf_rejects_scale_out_of_range(scale):
    with pytest.raises(ValueError):
        _pdf_options(scale=scale)


@pytest.mark.parametrize(
    "browser", ["chrome-headless", "edge-headless", "firefox-headless"]
)
def test_pdf_rejects_cli_backends(tmp_path, browser):
    hti = Html2Image(
        browser=browser, output_path=str(tmp_path), disable_logging=True
    )

    with pytest.raises(ValueError, match=r"pdf\(\)"):
        hti.pdf(html_str="Hello", save_as="cli.pdf")

    assert not (tmp_path / "cli.pdf").exists()


@pytest.mark.parametrize("save_as", ["image.pdf", ["image.png", "image.PDF"]])
def test_screenshot_rejects_pdf(tmp_path, save_as):
    hti = Html2Image(
        browser="chrome", output_path=str(tmp_path), disable_logging=True
    )

    with pytest.raises(ValueError, match=r"pdf\(\)"):
        hti.screenshot(html_str=["Hello", "Hello"], save_as=save_as)

    assert not list(tmp_path.iterdir())


def _pdf_page_sizes(path):
    """Returns the size of each page of a PDF file, in points."""
    data = Path(path).read_bytes()
    assert data.startswith(b"%PDF-")
    assert data.rstrip().endswith(b"%%EOF")
    boxes = re.findall(rb"/MediaBox\s*\[([^\]]*)\]", data)
    return [tuple(float(n) for n in box.split()[2:]) for box in boxes]


SLIDES_HTML = "".join(
    f'<section style="background:{color}">Slide {i}</section>'
    for i, color in enumerate(["red", "green", "blue"], 1)
)
SLIDES_CSS = """
body { margin: 0 }
section { width: 1280px; height: 720px; break-after: page; }
"""

PDF_BROWSERS = ["chrome", "edge", "firefox"]
# Edge runs the code of Chrome: it is only tried with the slides.
PDF_BROWSERS_WITHOUT_EDGE = ["chrome", "firefox"]


def _pdf_hti(browser, tmp_path):
    try:
        return Html2Image(
            browser=browser,
            output_path=str(tmp_path / "output"),
            temp_path=str(tmp_path / "temp"),
            disable_logging=True,
        )
    except FileNotFoundError:
        pytest.skip(f"'{browser}' executable not found on this machine")


@pytest.mark.parametrize("browser", PDF_BROWSERS)
def test_pdf_slides(tmp_path, browser):
    hti = _pdf_hti(browser, tmp_path)

    paths = hti.pdf(
        html_str=SLIDES_HTML,
        css_str=SLIDES_CSS,
        save_as=f"pdf_slides_{browser}.pdf",
        paper_size="slide",
    )

    assert _pdf_page_sizes(paths[0]) == [(960, 540)] * 3


@pytest.mark.parametrize("browser", PDF_BROWSERS_WITHOUT_EDGE)
@pytest.mark.parametrize("landscape", [None, True])
def test_pdf_a4(tmp_path, browser, landscape):
    hti = _pdf_hti(browser, tmp_path)

    paths = hti.pdf(
        html_str="<h1>Hello</h1>",
        save_as=f"pdf_a4_{browser}_{landscape}.pdf",
        landscape=landscape,
    )

    a4_points = (210 / 25.4 * 72, 297 / 25.4 * 72)
    expected = a4_points[::-1] if landscape else a4_points
    [size] = _pdf_page_sizes(paths[0])
    # Browsers round the page size: 595.92 x 841.92 for Chrome and Edge,
    # 596 x 842 for Firefox, instead of 595.28 x 841.89.
    assert size == pytest.approx(expected, abs=1)


@pytest.mark.parametrize("browser", PDF_BROWSERS_WITHOUT_EDGE)
def test_screenshot_after_pdf(tmp_path, browser):
    hti = _pdf_hti(browser, tmp_path)

    with hti:
        pdf_paths = hti.pdf(html_str="Hello", save_as=f"pdf_then_png_{browser}.pdf")
        png_paths = hti.screenshot(
            html_str='<body style="margin:0;background:blue"></body>',
            save_as=f"pdf_then_png_{browser}.png",
            size=(320, 240),
        )

    assert len(_pdf_page_sizes(pdf_paths[0])) == 1
    img = Image.open(png_paths[0]).convert("RGB")
    assert img.size == (320, 240)
    assert img.getpixel((0, 0)) == (0, 0, 255)
