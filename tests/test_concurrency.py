"""Tests of the `max_concurrency` option: captures run at the same time from
several threads, each in its own window of the same browser.

The tests that start a browser skip if it is not found on the current
machine. They only open local pages.
"""

from html2image import (
    Html2Image, BrowserError, PageLoadError, PageLoadTimeoutError,
)
from html2image.browsers import chrome_cdp, firefox_bidi
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from websocket import WebSocketConnectionClosedException, create_connection

import base64
import contextlib
import copy
import hashlib
import json
import os
import pickle
import pytest
import queue
import requests
import shutil
import signal
import socket
import threading
import time

# Edge runs the code of Chrome. It is only tried where the result depends on
# the browser itself: how it draws its windows, and how it is lost or closed.
BROWSERS = ["chrome", "firefox", "edge"]

MAX_CONCURRENCY = 3

SIZE = (320, 240)

COLORS = [
    (200, 30, 30), (30, 160, 30), (30, 30, 200),
    (200, 160, 0), (160, 0, 160), (0, 150, 150),
]

BLACK, WHITE = (0, 0, 0), (255, 255, 255)

BLOCKED_PAGE = "<script>while (true) {}</script>"

# Waits up to 5 seconds for the page to draw two images, as full page
# screenshots do, and tells whether it did and what the page sees.
DRAWN_JS = (
    "new Promise(done => {"
    " setTimeout(() => done(false), 5000);"
    " requestAnimationFrame(() => requestAnimationFrame(() => done(true)));"
    " }).then(drawn => JSON.stringify({drawn,"
    " visibility: document.visibilityState, focus: document.hasFocus()}))"
)


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


def _make_hti(browser, tmp_path, max_concurrency=MAX_CONCURRENCY):
    try:
        return Html2Image(
            browser=browser,
            output_path=str(tmp_path / "output"),
            temp_path=str(tmp_path / "temp"),
            size=SIZE,
            disable_logging=True,
            max_concurrency=max_concurrency,
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
    browser = hti.browser
    if isinstance(browser, firefox_bidi.FirefoxBiDi):
        # No other thread will read the answer at the same time.
        with browser._lock:
            return [context["url"] for context in browser._get_tree()]
    targets = requests.get(
        f"http://127.0.0.1:{browser._current_port}/json/list", timeout=5
    ).json()
    return [target["url"] for target in targets if target["type"] == "page"]


def _pid(hti):
    """Returns the process ID of the browser of `hti`."""
    browser = hti.browser
    if isinstance(browser, firefox_bidi.FirefoxBiDi):
        return browser.proc.pid
    return browser._browser_pid


def _loaded(hti, *names):
    """Returns the number of pages loaded from the temporary files of the
    images `names`. The folder of the files is named after the test."""
    files = [f"/{name}.html" for name in names]
    return sum(url.endswith(tuple(files)) for url in _pages(hti))


def _answers(port):
    """Returns True if a browser answers on `port`. Firefox answers this
    request with an error, but answers it."""
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


# Edge is tried with the capture in tiles, the only one that waits for each
# window to draw its page.
@pytest.mark.parametrize("browser, kind", [
    *(("chrome", kind) for kind in CAPTURES),
    *(("firefox", kind) for kind in CAPTURES),
    ("edge", "full_page_tiles"),
])
def test_captures_at_the_same_time(tmp_path, browser, kind):
    if kind == "full_page_tiles":
        pytest.importorskip("pyvips")
    hti = _make_hti(browser, tmp_path)

    with hti:
        pid = _pid(hti)
        assert len(_pages(hti)) == MAX_CONCURRENCY

        _capture_all(hti, COLORS, kind, kind)

        assert _pid(hti) == pid
        assert len(_pages(hti)) == MAX_CONCURRENCY


@pytest.mark.parametrize("browser", BROWSERS)
def test_every_window_draws_its_page(tmp_path, browser, monkeypatch):
    hti = _make_hti(browser, tmp_path)
    # The windows will keep their pages after the screenshots, to be read.
    # They are copies of the browser, made when the `with` block starts.
    hti.browser.isolate_pages = False
    monkeypatch.setattr(hti.browser, "_leave_page", lambda: None)

    with hti:
        _capture_all(hti, COLORS[:MAX_CONCURRENCY], "loaded")
        windows = hti.browser._windows
        assert len(windows) == MAX_CONCURRENCY
        with ThreadPoolExecutor(MAX_CONCURRENCY) as executor:
            states = list(executor.map(
                lambda window: window._evaluate(DRAWN_JS), windows
            ))

    # The state of each window, should one of them not draw.
    assert all(state["drawn"] for state in states), states


@pytest.mark.parametrize("browser", ["chrome", "firefox"])
def test_blocked_window_is_replaced(monkeypatch, tmp_path, browser):
    # The blocked page will not load within this time.
    wait_for_navigation = chrome_cdp.ChromeCDP._wait_for_navigation_complete
    monkeypatch.setattr(
        chrome_cdp.ChromeCDP, "_wait_for_navigation_complete",
        lambda self, nav_id: wait_for_navigation(self, nav_id, timeout=6),
    )
    monkeypatch.setattr(firefox_bidi, "BIDI_TIMEOUT", 6)
    hti = _make_hti(browser, tmp_path)

    with hti:
        pid = _pid(hti)
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
        assert len(_pages(hti)) == MAX_CONCURRENCY

        _capture_all(hti, COLORS[:MAX_CONCURRENCY], "after")
        assert _pid(hti) == pid


@pytest.mark.parametrize("browser", BROWSERS)
def test_lost_browser_is_restarted(tmp_path, browser):
    hti = _make_hti(browser, tmp_path)

    with hti:
        pid = _pid(hti)
        port = hti.browser._current_port
        os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        _wait_until(lambda: not _answers(port))

        with pytest.raises(BrowserError):
            hti.screenshot(html_str=_solid_page(BLACK), save_as="lost.png")

        new_pid = _pid(hti)
        assert new_pid != pid
        assert len(_pages(hti)) == MAX_CONCURRENCY
        _capture_all(hti, COLORS, "after")
        assert _pid(hti) == new_pid


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
        _wait_until(
            lambda: _loaded(hti, "blocked_0", "blocked_1") == len(calls)
        )

    # The captures in progress fail, and the browser is not started again.
    for call in calls:
        call.join()
        assert isinstance(call.error, BrowserError)
    assert hti.browser._ws is None
    assert not _answers(port)


@pytest.mark.parametrize("max_concurrency", [1, MAX_CONCURRENCY])
@pytest.mark.parametrize("browser", ["chrome"])
def test_temp_files_of_calls_at_the_same_time(
    tmp_path, browser, max_concurrency,
):
    hti = _make_hti(browser, tmp_path, max_concurrency)
    colors = COLORS[:4]
    # The files are copied in the same folder, and their color comes from
    # a stylesheet loaded there by each call.
    css = tmp_path / "style.css"
    css.write_text("".join(
        f".color_{index} {{ background: {_rgb(color)} }}"
        for index, color in enumerate(colors)
    ))
    # The HTML of `html_str` is named after `save_as`, and a copied file
    # keeps its name: each pair of pages has the same temporary name.
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


def _fake_hti(monkeypatch, tmp_path, screenshot, temp_path=None):
    """Returns an Html2Image object whose browser calls `screenshot`
    instead of taking a screenshot."""
    monkeypatch.setattr(chrome_cdp, "find_chrome", lambda executable: "c")
    hti = Html2Image(
        output_path=str(tmp_path / "output"),
        temp_path=str(temp_path or tmp_path / "temp"),
    )
    monkeypatch.setattr(hti.browser, "screenshot", screenshot)
    return hti


def _read(path):
    """Returns the name and the content of a loaded page."""
    with open(path) as page:
        return os.path.basename(path), page.read()


def _pages_with_the_same_temp_name(tmp_path, source):
    """Returns the options of a "first" and a "second" page that are loaded
    under the same temporary name, and that name."""
    if source == "html_str":
        return [
            dict(html_str=f"<p>{text}</p>", save_as=f"a.{extension}")
            for text, extension in [("first", "png"), ("second", "jpg")]
        ], "a.html"
    pages = []
    for text in ["first", "second"]:
        page = tmp_path / text / "page.html"
        page.parent.mkdir()
        page.write_text(f"<p>{text}</p>")
        pages.append(dict(html_file=str(page), save_as=f"{text}.png"))
    return pages, "page.html"


@pytest.mark.parametrize("source", ["html_str", "html_file"])
def test_calls_at_the_same_time_with_the_same_temp_name(
    monkeypatch, tmp_path, source
):
    loaded = threading.Barrier(2, timeout=10)
    seen = {}

    def screenshot(input, output_file, **options):
        # Both pages are loaded before either is read.
        loaded.wait()
        seen[output_file] = _read(input)

    hti = _fake_hti(monkeypatch, tmp_path, screenshot)
    pages, name = _pages_with_the_same_temp_name(tmp_path, source)

    with ThreadPoolExecutor(2) as executor:
        list(executor.map(lambda options: hti.screenshot(**options), pages))

    names = [seen[page["save_as"]][0] for page in pages]
    assert name in names and len(set(names)) == 2
    for page, text in zip(pages, ["first", "second"]):
        assert f"<p>{text}</p>" in seen[page["save_as"]][1]
    assert os.listdir(hti.temp_path) == []


def test_same_temp_path_through_a_link(monkeypatch, tmp_path):
    folder, link = tmp_path / "temp", tmp_path / "link"
    folder.mkdir()
    try:
        os.symlink(folder, link, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links cannot be created on this machine")
    loaded = threading.Barrier(2, timeout=10)
    seen = {}

    def screenshot(input, output_file, **options):
        # Both pages are loaded before either is read.
        loaded.wait()
        seen[output_file] = _read(input)

    # Two objects whose pages are loaded in the same folder.
    calls = [
        (_fake_hti(monkeypatch, tmp_path, screenshot, path), text, save_as)
        for path, text, save_as in [
            (folder, "first", "a.png"), (link, "second", "a.jpg"),
        ]
    ]

    with ThreadPoolExecutor(2) as executor:
        list(executor.map(
            lambda call: call[0].screenshot(
                html_str=f"<p>{call[1]}</p>", save_as=call[2]
            ),
            calls,
        ))

    assert len({seen[save_as][0] for _, _, save_as in calls}) == 2
    for _, text, save_as in calls:
        assert f"<p>{text}</p>" in seen[save_as][1]


def test_failed_call_gives_back_its_temp_name(monkeypatch, tmp_path):
    names = []

    def screenshot(input, **options):
        names.append(os.path.basename(input))
        if len(names) == 1:
            raise RuntimeError("capture failed")

    hti = _fake_hti(monkeypatch, tmp_path, screenshot)

    with pytest.raises(RuntimeError, match="capture failed"):
        hti.screenshot(html_str="<p>text</p>", save_as="a.png")
    hti.screenshot(html_str="<p>text</p>", save_as="a.png")

    assert names == ["a.html", "a.html"]
    assert os.listdir(hti.temp_path) == []


def test_temp_file_is_removed_if_its_page_cannot_be_loaded(
    monkeypatch, tmp_path
):
    loaded, release = threading.Event(), threading.Event()

    def screenshot(input, **options):
        loaded.set()
        release.wait(10)

    def load_str(**options):
        raise OSError("No space left on device")

    hti = _fake_hti(monkeypatch, tmp_path, screenshot)
    first = _Call(hti.screenshot, html_str="<p>first</p>", save_as="a.png")
    assert loaded.wait(10)
    monkeypatch.setattr(hti, "load_str", load_str)

    # The second call gets a name of its own, since a.html is in use.
    with pytest.raises(OSError, match="No space left"):
        hti.screenshot(html_str="<p>second</p>", save_as="a.png")
    assert os.listdir(hti.temp_path) == ["a.html"]

    release.set()
    first.join()
    assert first.error is None
    assert os.listdir(hti.temp_path) == []


def test_file_left_in_temp_path_keeps_its_name(monkeypatch, tmp_path):
    seen = []
    hti = _fake_hti(
        monkeypatch, tmp_path, lambda input, **options: seen.append(
            _read(input)
        ),
    )
    # As left by `keep_temp_files=True`, or by a program that was stopped.
    (tmp_path / "temp" / "a.html").write_text("<p>old</p>")

    hti.screenshot(html_str="<p>new</p>", save_as="a.png")

    [(name, content)] = seen
    assert name == "a.html" and "<p>new</p>" in content
    assert os.listdir(hti.temp_path) == []


@pytest.mark.parametrize("source", ["html_str", "html_file"])
def test_list_with_the_same_temp_name_twice(monkeypatch, tmp_path, source):
    seen = []
    hti = _fake_hti(
        monkeypatch, tmp_path, lambda input, **options: seen.append(
            _read(input)
        ),
    )
    pages, name = _pages_with_the_same_temp_name(tmp_path, source)

    # The pages of a list are captured one after the other, each under the
    # same name.
    hti.screenshot(
        **{source: [page[source] for page in pages]},
        save_as=[page["save_as"] for page in pages],
    )

    assert [page_name for page_name, _ in seen] == [name, name]
    for (_, content), text in zip(seen, ["first", "second"]):
        assert f"<p>{text}</p>" in content
    assert os.listdir(hti.temp_path) == []


def test_css_file_is_only_written_again_if_it_changed(monkeypatch, tmp_path):
    hti = _fake_hti(monkeypatch, tmp_path, lambda **options: None)
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


@pytest.mark.parametrize("max_concurrency", [1, MAX_CONCURRENCY])
@pytest.mark.parametrize("copy_of", [
    copy.deepcopy, lambda hti: pickle.loads(pickle.dumps(hti)),
], ids=["deepcopy", "pickle"])
@pytest.mark.parametrize("browser", ["chrome", "firefox"])
def test_objects_can_be_copied(
    monkeypatch, tmp_path, browser, copy_of, max_concurrency
):
    monkeypatch.setattr(chrome_cdp, "find_chrome", lambda executable: "c")
    monkeypatch.setattr(firefox_bidi, "find_firefox", lambda executable: "f")
    hti = Html2Image(
        browser=browser, temp_path=str(tmp_path),
        max_concurrency=max_concurrency,
    )

    browser = copy_of(hti).browser

    assert browser.max_concurrency == max_concurrency
    assert browser._lock is not hti.browser._lock
    # The copy can take `max_concurrency` screenshots at once, as the original.
    assert all(
        browser._slots.acquire(blocking=False) for _ in range(max_concurrency)
    )
    assert not browser._slots.acquire(blocking=False)


@pytest.mark.parametrize("browser", ["chrome", "firefox"])
def test_calls_without_with(tmp_path, browser):
    hti = _make_hti(browser, tmp_path)

    _capture_all(hti, COLORS[:2], "alone")

    assert hti.browser._ws is None
    assert hti.browser.proc is None


@pytest.mark.parametrize("browser", [
    "chrome-headless", "edge-headless", "firefox-headless",
])
def test_max_concurrency_needs_chrome_edge_or_firefox(browser):
    with pytest.raises(ValueError, match="max_concurrency works with"):
        Html2Image(browser=browser, max_concurrency=2)


@pytest.mark.parametrize("max_concurrency", [1, MAX_CONCURRENCY])
def test_window_flags_only_with_several_windows(monkeypatch, max_concurrency):
    monkeypatch.setattr(chrome_cdp, "find_chrome", lambda executable: "c")
    commands = []

    class Exited:
        def poll(self):
            return 0

    def popen(command, **options):
        commands.append(command)
        return Exited()

    monkeypatch.setattr(chrome_cdp.subprocess, "Popen", popen)
    replaced = chrome_cdp.ChromeCDP(max_concurrency=max_concurrency)
    replaced.flags = ["--mute-audio"]
    browsers = [
        Html2Image(max_concurrency=max_concurrency).browser,
        Html2Image(
            custom_flags=["--mute-audio"], max_concurrency=max_concurrency
        ).browser,
        replaced,
    ]

    for browser in browsers:
        browser._start_chrome()
        browser.__exit__()

    assert len(commands) == len(browsers)
    for command in commands:
        added = [flag in command for flag in chrome_cdp.WINDOW_FLAGS]
        assert added == [max_concurrency > 1] * len(added), command


@pytest.mark.parametrize("max_concurrency", [1, MAX_CONCURRENCY])
def test_file_processes_only_with_several_windows(
    monkeypatch, tmp_path, max_concurrency
):
    monkeypatch.setattr(firefox_bidi, "find_firefox", lambda executable: "f")
    browser = firefox_bidi.FirefoxBiDi(max_concurrency=max_concurrency)

    browser._write_profile_prefs(str(tmp_path))

    prefs = (tmp_path / "user.js").read_text(encoding="utf-8")
    added = f'user_pref("dom.ipc.processCount.file", {max_concurrency});'
    assert (added in prefs) == (max_concurrency > 1)
    assert ("processCount" in prefs) == (max_concurrency > 1)


@pytest.mark.parametrize("max_concurrency", [0, -1, 2.5, None])
@pytest.mark.parametrize("browser_class", [
    chrome_cdp.ChromeCDP, firefox_bidi.FirefoxBiDi,
])
def test_max_concurrency_is_checked(browser_class, max_concurrency):
    with pytest.raises(
        ValueError, match="max_concurrency should be 1 or more",
    ):
        browser_class(max_concurrency=max_concurrency)


class FakeFirefoxConnection:
    """The connection that the windows of Firefox share, on which the test
    plays Firefox: it reads the commands, and sends answers and events."""

    def __init__(self):
        self.commands = queue.Queue()
        self.messages = queue.Queue()

    def settimeout(self, timeout):
        pass

    def send(self, payload):
        self.commands.put(json.loads(payload))

    def recv(self):
        message = self.messages.get()
        if isinstance(message, Exception):
            raise message
        return json.dumps(message)

    def close(self):
        self.messages.put(WebSocketConnectionClosedException("closed"))

    def command(self):
        """Returns the next command sent by a window."""
        return self.commands.get(timeout=5)

    def answer(self, command, result):
        self.messages.put(
            {"type": "success", "id": command["id"], "result": result}
        )


@pytest.fixture
def firefox():
    connection = FakeFirefoxConnection()
    yield connection
    # Ends the thread that reads the messages.
    connection.close()


def _firefox_with_windows(monkeypatch, firefox):
    """Returns a FirefoxBiDi object whose windows, "first" and "second",
    share the connection `firefox`."""
    monkeypatch.setattr(firefox_bidi, "find_firefox", lambda executable: "f")
    browser = firefox_bidi.FirefoxBiDi(max_concurrency=2)
    browser._connection = firefox_bidi._SharedConnection(firefox)
    browser._ws = browser._connection.channel()
    browser._context_id = "first"
    browser._downloads_reported = True
    first = browser._open_window(new_window=False)
    with ThreadPoolExecutor(1) as executor:
        opening = executor.submit(browser._open_window)
        command = firefox.command()
        assert command["method"] == "browsingContext.create"
        assert command["params"] == {"type": "window"}
        firefox.answer(command, {"context": "second"})
        second = opening.result(timeout=5)
    return browser, first, second


def test_windows_share_one_connection(monkeypatch, firefox):
    browser, first, second = _firefox_with_windows(monkeypatch, firefox)

    with ThreadPoolExecutor(2) as executor:
        navigations = [
            executor.submit(window._navigate, "http://127.0.0.1:1/")
            for window in (first, second)
        ]
        commands = {}
        for _ in range(2):
            command = firefox.command()
            commands[command["params"]["context"]] = command
        # Firefox reports a download in the second window, and answers
        # this window first.
        firefox.messages.put({
            "type": "event",
            "method": firefox_bidi.DOWNLOAD_EVENT,
            "params": {"context": "second", "navigation": "other"},
        })
        for context in ["second", "first"]:
            firefox.answer(commands[context], {"navigation": context})
        # Each window then asks for the status of Firefox.
        for _ in range(2):
            command = firefox.command()
            assert command["method"] == "session.status"
            firefox.answer(command, {"ready": False})

        navigations[0].result(timeout=5)
        with pytest.raises(PageLoadError, match="started a download"):
            navigations[1].result(timeout=5)

    # Each command had a number of its own.
    numbers = [command["id"] for command in commands.values()]
    assert len(set(numbers)) == len(numbers)


def test_lost_connection_fails_every_window(monkeypatch, firefox):
    browser, first, second = _firefox_with_windows(monkeypatch, firefox)

    with ThreadPoolExecutor(2) as executor:
        waits = [
            executor.submit(window._get_tree) for window in (first, second)
        ]
        for _ in range(2):
            firefox.command()
        firefox.messages.put(ConnectionResetError(10054, "Connection reset"))

        for wait in waits:
            with pytest.raises(BrowserError, match="connection .* was lost"):
                wait.result(timeout=5)

    # The next commands fail at once, as with a connection of their own.
    with pytest.raises(BrowserError, match="connection .* was lost"):
        first._get_tree()
    assert not browser._close_window(second)


def test_closed_window_fails_at_once(monkeypatch, firefox):
    browser, first, second = _firefox_with_windows(monkeypatch, firefox)

    with ThreadPoolExecutor(1) as executor:
        wait = executor.submit(first._get_tree)
        firefox.command()
        first._ws.close()

        with pytest.raises(BrowserError, match="connection .* was lost"):
            wait.result(timeout=5)

    # The other window goes on.
    with ThreadPoolExecutor(1) as executor:
        wait = executor.submit(second._get_tree)
        firefox.answer(firefox.command(), {"contexts": [{"context": "x"}]})
        assert wait.result(timeout=5) == [{"context": "x"}]


@contextlib.contextmanager
def _silent_firefox(answer=None):
    """Yields a WebSocket connection to a local server that sends nothing
    once connected, as a Firefox that stopped answering.

    With `answer`, the server first sends it, once it receives a command.
    """
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    clients = []

    def accept():
        client, _ = server.accept()
        clients.append(client)
        request = client.recv(4096).decode()
        key = next(
            line.split(":", 1)[1].strip() for line in request.split("\r\n")
            if line.lower().startswith("sec-websocket-key")
        )
        accepted = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
        ).digest()).decode()
        client.sendall((
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accepted}\r\n\r\n"
        ).encode())
        if answer is not None and client.recv(4096):
            # A short text message, as a single WebSocket frame.
            text = json.dumps(answer).encode()
            client.sendall(bytes([0x81, len(text)]) + text)

    threading.Thread(target=accept, daemon=True).start()
    port = server.getsockname()[1]
    try:
        yield create_connection(f"ws://127.0.0.1:{port}/", timeout=5)
    finally:
        for client in clients:
            client.close()
        server.close()


def test_shared_connection_closes_while_firefox_is_silent():
    with _silent_firefox() as ws:
        connection = firefox_bidi._SharedConnection(ws)
        channel = connection.channel()
        waiting = _Call(channel.recv)

        closing = _Call(connection.close)

        closing.join(5)
        assert not closing.is_alive()
        waiting.join(5)
        assert isinstance(waiting.error, WebSocketConnectionClosedException)
        with pytest.raises(BrowserError, match="connection .* was lost"):
            connection.send(channel, "session.status", {})


class _ExitedProcess:
    """Stands for the process of Firefox, so that no process is stopped."""

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def test_exit_returns_while_firefox_is_silent(monkeypatch, tmp_path):
    monkeypatch.setattr(firefox_bidi, "find_firefox", lambda executable: "f")
    browser = firefox_bidi.FirefoxBiDi(max_concurrency=2, disable_logging=True)
    profile = tmp_path / "profile"
    profile.mkdir()
    # Firefox will answer browser.close, the first command on the shared
    # connection, but will never close this connection.
    closed = {"type": "success", "id": 1, "result": {}}

    with _silent_firefox(answer=closed) as ws:
        # As inside a `with` block, with a window in use, which waits for
        # an answer.
        browser.proc = _ExitedProcess()
        browser._profile_dir = str(profile)
        browser._connection = firefox_bidi._SharedConnection(ws)
        browser._ws = browser._connection.channel()
        browser._context_id = "first"
        window = browser._open_window(new_window=False)
        browser._windows = []
        capture = _Call(
            window._bidi_recv_until, predicate=lambda message: False
        )

        exiting = _Call(browser.__exit__)

        exiting.join(5)
        assert not exiting.is_alive()
        assert exiting.error is None
        capture.join(5)
        assert isinstance(capture.error, BrowserError)
    assert not profile.exists()
