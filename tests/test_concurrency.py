"""Tests of the `concurrency` option: captures run at the same time from
several threads, each in its own window of the same browser.

The tests that start a browser skip if it is not found on the current
machine. They only open local pages.
"""

from html2image import Html2Image, BrowserError, PageLoadTimeoutError
from html2image.browsers import chrome_cdp
from concurrent.futures import ThreadPoolExecutor
from PIL import Image

import os
import pytest
import requests
import shutil
import signal
import threading
import time

BROWSERS = ["chrome", "edge"]

CONCURRENCY = 3

SIZE = (320, 240)

COLORS = [
    (200, 30, 30), (30, 160, 30), (30, 30, 200),
    (200, 160, 0), (160, 0, 160), (0, 150, 150),
]

BLACK, WHITE = (0, 0, 0), (255, 255, 255)

BLOCKED_PAGE = "<script>while (true) {}</script>"


def _rgb(color):
    return "rgb(%d, %d, %d)" % color


def _solid_page(color):
    return f'<body style="margin: 0; background: {_rgb(color)}"></body>'


# The element is below the window, which is 240 pixels high.
def _element_page(color):
    return (
        '<body style="margin: 0; background: white">'
        '<div id="card" style="position: absolute; left: 30px; top: 700px; '
        f'width: 150px; height: 80px; background: {_rgb(color)}"></div>'
        '</body>'
    )


def _long_page(color, fixed_header=False):
    header = (
        '<div style="position: fixed; top: 0; left: 0; right: 0; '
        'height: 20px; background: black"></div>'
    ) if fixed_header else ""
    return (
        f'<body style="margin: 0; background: {_rgb(color)}">'
        f'{header}<div style="height: 1500px"></div></body>'
    )


def _colors(path):
    """Returns the size of an image and its colors, most used first."""
    img = Image.open(path).convert("RGB")
    colors = sorted(img.getcolors(1 << 24), reverse=True)
    return img.size, [color for _, color in colors]


# For each kind of capture: the options of `screenshot()`, and the size and
# colors of the image of a page in `color`.
CAPTURES = {
    "window": (
        lambda color: dict(html_str=_solid_page(color)),
        lambda color: (SIZE, [color]),
    ),
    "selector": (
        lambda color: dict(html_str=_element_page(color), selector="#card"),
        lambda color: ((150, 80), [color]),
    ),
    "full_page": (
        lambda color: dict(html_str=_long_page(color), full_page=True),
        lambda color: ((SIZE[0], 1500), [color]),
    ),
    # A fixed element makes the page be captured in tiles.
    "full_page_tiles": (
        lambda color: dict(
            html_str=_long_page(color, fixed_header=True), full_page=True
        ),
        lambda color: ((SIZE[0], 1500), [color, BLACK]),
    ),
}


def _make_hti(browser, tmp_path, concurrency=CONCURRENCY):
    try:
        return Html2Image(
            browser=browser,
            output_path=str(tmp_path / "output"),
            temp_path=str(tmp_path / "temp"),
            size=SIZE,
            disable_logging=True,
            concurrency=concurrency,
        )
    except FileNotFoundError:
        pytest.skip(f"'{browser}' executable not found on this machine")


def _capture_all(hti, colors, prefix, kind="window"):
    """Captures one page per color, all at the same time, and checks each
    image."""
    options, expected = CAPTURES[kind]

    def capture(index):
        [path] = hti.screenshot(
            save_as=f"{prefix}_{index}.png", **options(colors[index])
        )
        return path

    with ThreadPoolExecutor(len(colors)) as executor:
        paths = list(executor.map(capture, range(len(colors))))

    for path, color in zip(paths, colors):
        assert _colors(path) == expected(color), path


def _pages(hti):
    """Returns the URLs of the pages open in the browser of `hti`."""
    targets = requests.get(
        f"http://127.0.0.1:{hti.browser._current_port}/json/list", timeout=5
    ).json()
    return [target["url"] for target in targets if target["type"] == "page"]


def _loaded(hti, name):
    """Returns the number of pages whose temporary file is named after
    `name`. The folder of the file is named after the test."""
    return sum(f"/{name}_" in url for url in _pages(hti))


def _answers(port):
    """Returns True if a browser answers on `port`."""
    try:
        requests.get(f"http://127.0.0.1:{port}/json/version", timeout=5)
    except requests.ConnectionError:
        return False
    return True


def _wait_until(condition, timeout=10):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.1)


class _Call(threading.Thread):
    """Calls `function(**kwargs)` in a thread, and keeps its error."""

    def __init__(self, function, **kwargs):
        super().__init__(daemon=True)
        self.function = function
        self.kwargs = kwargs
        self.error = None
        self.start()

    def run(self):
        try:
            self.function(**self.kwargs)
        except Exception as error:
            self.error = error


@pytest.mark.parametrize("kind", CAPTURES)
@pytest.mark.parametrize("browser", BROWSERS)
def test_captures_at_the_same_time(tmp_path, browser, kind):
    if kind == "full_page_tiles":
        pytest.importorskip("pyvips")
    hti = _make_hti(browser, tmp_path)

    with hti:
        pid = hti.browser._browser_pid
        assert len(_pages(hti)) == CONCURRENCY

        _capture_all(hti, COLORS, kind, kind)

        assert hti.browser._browser_pid == pid
        assert len(_pages(hti)) == CONCURRENCY


@pytest.mark.parametrize("browser", BROWSERS)
def test_blocked_window_is_replaced(monkeypatch, tmp_path, browser):
    # The blocked page will not load within this time.
    wait_for_navigation = chrome_cdp.ChromeCDP._wait_for_navigation_complete
    monkeypatch.setattr(
        chrome_cdp.ChromeCDP, "_wait_for_navigation_complete",
        lambda self, nav_id: wait_for_navigation(self, nav_id, timeout=6),
    )
    hti = _make_hti(browser, tmp_path)

    with hti:
        pid = hti.browser._browser_pid
        blocked = _Call(
            hti.screenshot, html_str=BLOCKED_PAGE, save_as="blocked.png"
        )
        _wait_until(lambda: _loaded(hti, "blocked"))

        # The other windows go on while the page is blocked.
        _capture_all(hti, COLORS[:4], "during")
        assert blocked.is_alive()

        blocked.join()
        assert isinstance(blocked.error, PageLoadTimeoutError)
        _wait_until(lambda: not _loaded(hti, "blocked"))
        assert len(_pages(hti)) == CONCURRENCY

        _capture_all(hti, COLORS[:CONCURRENCY], "after")
        assert hti.browser._browser_pid == pid


@pytest.mark.parametrize("browser", BROWSERS)
def test_lost_browser_is_restarted(tmp_path, browser):
    hti = _make_hti(browser, tmp_path)

    with hti:
        pid = hti.browser._browser_pid
        port = hti.browser._current_port
        os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        _wait_until(lambda: not _answers(port))

        with pytest.raises(BrowserError):
            hti.screenshot(html_str=_solid_page(BLACK), save_as="lost.png")

        new_pid = hti.browser._browser_pid
        assert new_pid != pid
        assert len(_pages(hti)) == CONCURRENCY
        _capture_all(hti, COLORS, "after")
        assert hti.browser._browser_pid == new_pid


@pytest.mark.parametrize("browser", BROWSERS)
def test_exit_during_captures(tmp_path, browser):
    hti = _make_hti(browser, tmp_path)

    with hti:
        port = hti.browser._current_port
        calls = [
            _Call(
                hti.screenshot, html_str=BLOCKED_PAGE,
                save_as=f"blocked_{i}.png",
            )
            for i in range(2)
        ]
        _wait_until(lambda: _loaded(hti, "blocked") == len(calls))

    # The captures in progress fail, and the browser is not started again.
    for call in calls:
        call.join()
        assert isinstance(call.error, BrowserError)
    assert hti.browser._ws is None
    assert not _answers(port)


@pytest.mark.parametrize("concurrency", [1, CONCURRENCY])
@pytest.mark.parametrize("browser", BROWSERS)
def test_temp_files_of_calls_at_the_same_time(tmp_path, browser, concurrency):
    hti = _make_hti(browser, tmp_path, concurrency)
    colors = COLORS[:4]
    # The files are copied in the same folder, and their color comes from
    # a stylesheet loaded there by each call.
    css = tmp_path / "style.css"
    css.write_text("".join(
        f".color_{index} {{ background: {_rgb(color)} }}"
        for index, color in enumerate(colors)
    ))
    # Before, the HTML of `html_str` was named after `save_as`, and a
    # copied file kept its name: each pair of pages used one file.
    files = []
    for index in range(len(colors)):
        folder = tmp_path / f"folder_{index}"
        folder.mkdir()
        (folder / "page.html").write_text(
            '<link rel="stylesheet" href="style.css">'
            f'<body class="color_{index}" style="margin: 0"></body>'
        )
        files.append(str(folder / "page.html"))
    pages = [
        dict(html_str=_solid_page(color), save_as=f"string.{extension}")
        for color, extension in zip(colors[:2], ("png", "jpeg"))
    ] + [
        dict(html_file=path, css_file=str(css), save_as=f"file_{index}.png")
        for index, path in enumerate(files)
    ]
    expected = colors[:2] + colors

    with hti:
        with ThreadPoolExecutor(len(pages)) as executor:
            paths = list(executor.map(
                lambda options: hti.screenshot(**options)[0], pages
            ))

    for path, color in zip(paths, expected):
        pixel = Image.open(path).convert("RGB").getpixel((10, 10))
        # JPEG images are not exact.
        assert all(abs(a - b) <= 8 for a, b in zip(pixel, color)), path
    assert os.listdir(hti.temp_path) == ["style.css"]


def test_css_file_is_only_written_again_if_it_changed(monkeypatch, tmp_path):
    monkeypatch.setattr(chrome_cdp, "find_chrome", lambda executable: "c")
    hti = Html2Image(
        output_path=str(tmp_path / "output"),
        temp_path=str(tmp_path / "temp"),
    )
    monkeypatch.setattr(hti.browser, "screenshot", lambda **options: None)
    copies = []
    copyfile = shutil.copyfile

    def record_copy(src, dst):
        copies.append(os.path.basename(dst))
        return copyfile(src, dst)

    monkeypatch.setattr(shutil, "copyfile", record_copy)
    css = tmp_path / "style.css"

    for content in ["p { color: red }"] * 2 + ["p { color: blue }"]:
        css.write_text(content)
        hti.screenshot(html_str="<p>text</p>", css_file=str(css))

    assert copies == ["style.css"] * 2
    assert (tmp_path / "temp" / "style.css").read_text() == "p { color: blue }"


@pytest.mark.parametrize("browser", BROWSERS)
def test_calls_without_with(tmp_path, browser):
    hti = _make_hti(browser, tmp_path)

    _capture_all(hti, COLORS[:2], "alone")

    assert hti.browser._ws is None
    assert hti.browser._user_data_dir is None


@pytest.mark.parametrize("browser", [
    "chrome-headless", "edge-headless", "firefox", "firefox-headless",
])
def test_concurrency_needs_chrome_or_edge(browser):
    with pytest.raises(ValueError, match="concurrency works with"):
        Html2Image(browser=browser, concurrency=2)


@pytest.mark.parametrize("concurrency", [0, -1, 2.5, None])
def test_concurrency_is_checked(concurrency):
    with pytest.raises(ValueError, match="concurrency should be 1 or more"):
        chrome_cdp.ChromeCDP(concurrency=concurrency)
