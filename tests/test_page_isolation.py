"""Tests of `isolate_pages`, and of the browser kept for all the pages of a
call, with fake browsers.

The browsers are replaced where they would start, stop, open, close or
clean up a page, and take a screenshot. What they would do is noted in a
list of events. The real `_window()` and `_render()` run. The tests with a
real browser are at the end of this file, and in test_own_browser.py.
"""

from html2image import (
    Html2Image,
    BrowserError,
    CaptureTooLargeError,
    PageLoadError,
)
from html2image.browsers import chrome_cdp, chromium, firefox_bidi
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from test_concurrency import _pages
from test_own_browser import (
    BLUE, GREEN, LEAVE_STATE, RED, SHOW_STATE, STATES, _page_of_color,
    found_state,
)
from websocket import WebSocketTimeoutException

import json
import os
import pytest
import threading
import time

URLS = [f"http://127.0.0.1:1/p{index}" for index in (1, 2, 3)]

NAMES = ["p1.png", "p2.png", "p3.png"]


class FakeBrowser:
    """Replaces the browser of `hti`, see the docstring of this file.

    A page whose name is in `errors` raises its error. Without
    `private_pages`, the browser cannot open a private context, as Firefox
    before version 124.
    """

    def __init__(self, monkeypatch, hti, errors=None, private_pages=True):
        self.browser = browser = hti.browser
        self.events = []
        self.errors = errors or {}
        self.private_pages = private_pages
        stop = (
            "_stop_chrome" if isinstance(browser, chrome_cdp.ChromeCDP)
            else "_stop_firefox"
        )
        for name, method in [
            ("_start_chrome", lambda: None),
            ("_connect_ws", self.start),
            (stop, self.stop),
            ("_open_private_page", self.open_private_page),
            ("_close_page", lambda: self.events.append("close page")),
            ("_leave_page", lambda: self.events.append("leave page")),
            ("screenshot", self.screenshot),
        ]:
            monkeypatch.setattr(browser, name, method, raising=False)

    def start(self, *args):
        self.events.append("start")
        self.browser._ws = object()

    def stop(self):
        self.events.append("stop")
        self.browser._ws = None

    def open_private_page(self, new_window=False, blank_start_page=False):
        self.events.append("private page")
        if not self.private_pages:
            return False
        if blank_start_page:
            self.events.append("blank start page")
        return True

    def screenshot(self, input, output_path, output_file="screenshot.png",
                   **options):
        self.browser._normalize_input(input)
        with self.browser._window():
            name = os.path.splitext(os.path.basename(input))[0]
            self.events.append(name)
            if name in self.errors:
                raise self.errors[name]
            with open(os.path.join(output_path, output_file), "w"):
                pass

    def pages(self):
        """The names of the pages, each with what came before it: "start"
        or "private page"."""
        events = [event for event in self.events if event != "blank start page"]
        return [
            (events[index - 1], event)
            for index, event in enumerate(events)
            if event.startswith("p") and not event.startswith("private")
        ]


@pytest.fixture(params=["chrome", "firefox"])
def make_hti(request, monkeypatch, tmp_path):
    """Returns an Html2Image with `options`, and its fake browser."""
    monkeypatch.setattr(chrome_cdp, "find_chrome", lambda executable: "c")
    monkeypatch.setattr(firefox_bidi, "find_firefox", lambda executable: "f")

    def make(errors=None, private_pages=True, **options):
        hti = Html2Image(
            browser=request.param,
            output_path=str(tmp_path / "output"),
            temp_path=str(tmp_path / "temp"),
            **options,
        )
        return hti, FakeBrowser(monkeypatch, hti, errors, private_pages)

    return make


def _images(hti):
    return sorted(os.listdir(hti.output_path))


def test_a_list_starts_one_browser(make_hti):
    hti, fake = make_hti()

    paths = hti.screenshot(url=URLS, save_as=NAMES)

    # The first page uses the page that the browser opened, which the next
    # page leaves blank.
    assert fake.events == [
        "start", "p1",
        "private page", "blank start page", "p2", "close page",
        "private page", "p3", "close page", "stop",
    ]
    assert [os.path.basename(path) for path in paths] == NAMES
    assert hti.browser._ws is None


def test_shared_pages_in_a_list(make_hti):
    hti, fake = make_hti(isolate_pages=False)

    hti.screenshot(url=URLS, save_as=NAMES)

    # Each page is left in the same tab, which is cleaned up after it.
    assert fake.events == [
        "start", "p1", "leave page", "p2", "leave page", "p3", "leave page",
        "stop",
    ]


@pytest.mark.parametrize("isolate_pages, events", [
    (True, [
        "start", "private page", "p1", "close page",
        "private page", "p2", "close page", "stop",
    ]),
    (False, ["start", "p1", "leave page", "p2", "leave page", "stop"]),
])
def test_with_block(make_hti, isolate_pages, events):
    hti, fake = make_hti(isolate_pages=isolate_pages)

    with hti:
        hti.screenshot(url=URLS[0], save_as="p1.png")
        hti.screenshot(url=URLS[1], save_as="p2.png")

    assert fake.events == events


def test_one_page_per_call(make_hti):
    hti, fake = make_hti()

    hti.screenshot(url=URLS[0], save_as="p1.png")
    hti.screenshot_url(URLS[1], output_file="p2.png")

    # Nothing more than before.
    assert fake.events == ["start", "p1", "stop", "start", "p2", "stop"]


def test_a_call_without_page_starts_nothing(make_hti):
    hti, fake = make_hti()

    assert hti.screenshot() == []
    assert fake.events == []


@pytest.mark.parametrize("error, events", [
    # The page is closed, and the browser is closed at the end of the call.
    (PageLoadError("Navigation failed"), ["close page", "stop"]),
    # The browser may be unusable: it is closed at once, without being
    # started again.
    (BrowserError("The connection to the browser was lost."), ["stop"]),
])
def test_error_in_the_middle_of_a_list(make_hti, error, events):
    hti, fake = make_hti(errors={"p2": error})

    with pytest.raises(type(error)):
        hti.screenshot(url=URLS, save_as=NAMES)

    assert fake.events == [
        "start", "p1", "private page", "blank start page", "p2", *events,
    ]
    assert _images(hti) == ["p1.png"]


@pytest.mark.parametrize("error, events", [
    # The tab is cleaned up as after the other pages.
    (PageLoadError("Navigation failed"), ["leave page", "stop"]),
    # The browser may be unusable: it is closed at once.
    (BrowserError("The connection to the browser was lost."), ["stop"]),
])
def test_error_in_the_middle_of_shared_pages(make_hti, error, events):
    hti, fake = make_hti(errors={"p2": error}, isolate_pages=False)

    with pytest.raises(type(error)):
        hti.screenshot(url=URLS, save_as=NAMES)

    assert fake.events == ["start", "p1", "leave page", "p2", *events]


def test_invalid_url_in_the_middle_of_a_list(make_hti):
    hti, fake = make_hti()

    with pytest.raises(ValueError, match="Invalid IPv6 URL"):
        hti.screenshot(
            url=[URLS[0], "http://[malformed", URLS[2]], save_as=NAMES
        )

    assert fake.events == ["start", "p1", "stop"]
    assert _images(hti) == ["p1.png"]


def test_too_large_page_in_the_middle_of_a_list(make_hti):
    hti, fake = make_hti(errors={"p2": CaptureTooLargeError("Too large")})

    with pytest.raises(CaptureTooLargeError) as excinfo:
        hti.screenshot(url=URLS, save_as=NAMES, full_page=True)

    # The other pages are captured first, in the same browser.
    assert fake.events.count("start") == 1
    assert fake.events[-2:] == ["close page", "stop"]
    assert [os.path.basename(path) for path in excinfo.value.paths] == [
        "p1.png", "p3.png",
    ]


def test_lost_browser_in_a_with_block_is_restarted(make_hti):
    hti, fake = make_hti(errors={"p1": BrowserError("Lost")})

    with hti:
        with pytest.raises(BrowserError):
            hti.screenshot(url=URLS[0], save_as="p1.png")
        hti.screenshot(url=URLS[1], save_as="p2.png")

    assert fake.events == [
        "start", "private page", "p1", "stop", "start",
        "private page", "p2", "close page", "stop",
    ]


def test_browser_without_private_pages_is_started_for_each_page(make_hti):
    hti, fake = make_hti(private_pages=False)

    hti.screenshot(url=URLS, save_as=NAMES)

    # As before, each page has a new browser.
    assert fake.events == [
        "start", "p1",
        "private page", "stop", "start", "p2",
        "private page", "stop", "start", "p3", "stop",
    ]


def test_page_that_cannot_be_closed(make_hti, monkeypatch):
    hti, fake = make_hti()

    def close_page():
        fake.events.append("close page")
        raise BrowserError("The connection to the browser was lost.")

    monkeypatch.setattr(hti.browser, "_close_page", close_page)

    # The images are saved, and the next page has a private context all
    # the same.
    paths = hti.screenshot(url=URLS, save_as=NAMES)

    assert len(paths) == 3
    assert fake.pages() == [
        ("start", "p1"), ("private page", "p2"), ("private page", "p3"),
    ]


def test_shared_tab_that_cannot_be_cleaned_up(make_hti, monkeypatch):
    hti, fake = make_hti(isolate_pages=False)

    def leave_page():
        fake.events.append("leave page")
        raise BrowserError("Timed out after 30s waiting for CDP response.")

    monkeypatch.setattr(hti.browser, "_leave_page", leave_page)

    # The images are saved, and the next pages are loaded all the same.
    paths = hti.screenshot(url=URLS, save_as=NAMES)

    assert len(paths) == 3
    assert fake.events.count("leave page") == 3


def test_files_of_shared_pages(make_hti, tmp_path):
    hti, fake = make_hti(isolate_pages=False)
    files = []
    for folder in ("a", "b"):
        page = tmp_path / folder / "page.html"
        page.parent.mkdir()
        page.write_text("<p>page</p>")
        files.append(str(page))

    with hti:
        # The same `save_as` twice, then two files of the same name.
        hti.screenshot(html_str="<p>first</p>", save_as="p1.png")
        hti.screenshot(html_str="<p>second</p>", save_as="p1.png")
        hti.screenshot(html_file=files, save_as=["p2.png", "p3.png"])

    names = [event for event in fake.events if event.startswith("p")]
    if isinstance(hti.browser, firefox_bidi.FirefoxBiDi):
        # Firefox would take two pages loaded from the same file for the
        # same origin, and could draw the second one with the <style>
        # sheets of the first.
        assert len(set(names)) == 4
        assert [name.split("_")[0] for name in names] == [
            "p1", "p1", "page", "page",
        ]
    else:
        # Chrome writes the name of the file in the title of a PDF that has
        # no <title>.
        assert names == ["p1", "p1", "page", "page"]
    assert os.listdir(hti.temp_path) == []


def test_calls_from_two_threads(make_hti):
    hti, fake = make_hti()
    errors = []

    def call(prefix):
        try:
            hti.screenshot(
                url=[f"http://127.0.0.1:1/p_{prefix}{index}"
                     for index in range(3)],
                save_as=[f"{prefix}{index}.png" for index in range(3)],
            )
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=call, args=(prefix,))
               for prefix in "ab"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert errors == []
    assert len(_images(hti)) == 6
    # Each page has a new browser or a new private context.
    assert {before for before, _ in fake.pages()} <= {"start", "private page"}
    assert hti.browser._ws is None


@pytest.mark.parametrize("browser", [
    "chrome-headless", "edge-headless", "firefox-headless",
])
def test_shared_pages_need_chrome_edge_or_firefox(browser):
    with pytest.raises(ValueError, match="isolate_pages=False works with"):
        Html2Image(browser=browser, isolate_pages=False)


def test_legacy_browser_takes_each_screenshot_alone(
    monkeypatch, tmp_path, capsys
):
    commands = []
    monkeypatch.setattr(
        chromium.subprocess, "run",
        lambda command, **options: commands.append(command),
    )
    try:
        hti = Html2Image(
            browser="chrome-headless", output_path=str(tmp_path),
            temp_path=str(tmp_path / "temp"),
        )
    except FileNotFoundError:
        pytest.skip("'chrome-headless' executable not found on this machine")

    hti.screenshot(html_str=["<p>a</p>", "<p>b</p>"], save_as=["a.png", "b.png"])

    assert len(commands) == 2
    assert "Context manager" not in capsys.readouterr().out


# The commands that open and close a private page.

class FakeConnection:
    """Answers each command with `answers[method]`, or an empty result,
    after the messages of `before`."""

    def __init__(self, answers, before=()):
        self.answers = answers
        self.commands = []
        self.messages = [json.dumps(message) for message in before]

    def send(self, payload):
        command = json.loads(payload)
        self.commands.append(command)
        answer = {"id": command["id"]}
        if "sessionId" in command:
            # The answer of a page comes in its session, as with Chrome.
            answer["sessionId"] = command["sessionId"]
        answer.update(self.answers.get(command["method"], {"result": {}}))
        self.messages.append(json.dumps(answer))

    def settimeout(self, timeout):
        pass

    def recv(self):
        if not self.messages:
            raise WebSocketTimeoutException()
        return self.messages.pop(0)


def test_chrome_private_page(monkeypatch):
    monkeypatch.setattr(chrome_cdp, "find_chrome", lambda executable: "c")
    browser = chrome_cdp.ChromeCDP()
    browser._session_id, browser._target_id = "previous", "start"
    browser._ws = FakeConnection({
        "Target.createBrowserContext": {
            "result": {"browserContextId": "context"},
        },
        "Target.createTarget": {"result": {"targetId": "page"}},
        "Target.attachToTarget": {"result": {"sessionId": "session"}},
    }, before=[
        # Sent by a page that was closed, which is ignored.
        {"sessionId": "closed", "method": "Inspector.detached",
         "params": {"reason": "target_closed"}},
    ])

    assert browser._open_private_page(blank_start_page=True)
    assert browser._session_id == "session"
    browser._close_page()

    commands = browser._ws.commands
    assert [command["method"] for command in commands] == [
        "Page.navigate",
        "Target.createBrowserContext",
        "Browser.setDownloadBehavior",
        "Target.createTarget",
        "Target.attachToTarget",
        "Target.disposeBrowserContext",
    ]
    # The page that Chrome opened is left blank, in its own session.
    assert commands[0]["params"] == {"url": "about:blank"}
    assert commands[0]["sessionId"] == "previous"
    commands = commands[1:]
    # The downloads are refused in the private context.
    assert commands[1]["params"] == {
        "behavior": "deny", "browserContextId": "context",
    }
    # Chrome cannot open a tab in a context without a window.
    assert commands[2]["params"]["newWindow"] is True
    # All are sent to Chrome itself, not to a page.
    assert not any("sessionId" in command for command in commands)
    assert browser._session_id is browser._browser_context_id is None


def test_chrome_ignores_page_messages_without_a_session(monkeypatch):
    monkeypatch.setattr(chrome_cdp, "find_chrome", lambda executable: "c")
    browser = chrome_cdp.ChromeCDP()

    assert browser._message_matches_current_session({"id": 1})
    assert not browser._message_matches_current_session(
        {"sessionId": "page", "method": "Inspector.detached"}
    )


@pytest.mark.parametrize("answer, opened", [
    ({"result": {"userContext": "user"}}, True),
    # Before version 124.
    ({"type": "error", "error": "unknown command"}, False),
])
def test_firefox_private_page(monkeypatch, answer, opened):
    monkeypatch.setattr(firefox_bidi, "find_firefox", lambda executable: "f")
    browser = firefox_bidi.FirefoxBiDi()
    browser._context_id = "start"
    browser._ws = FakeConnection({
        "browser.createUserContext": answer,
        "browsingContext.create": {"result": {"context": "tab"}},
    })

    assert browser._open_private_page(blank_start_page=True) is opened

    if opened:
        assert browser._context_id == "tab"
        commands = browser._ws.commands
        assert commands[1]["params"] == {"type": "tab", "userContext": "user"}
        # The tab that Firefox opened is left blank once the new one is open.
        assert commands[2]["method"] == "browsingContext.navigate"
        assert commands[2]["params"] == {
            "context": "start", "url": "about:blank", "wait": "complete",
        }
        browser._close_page()
        assert browser._ws.commands[-1]["method"] == (
            "browser.removeUserContext"
        )
        assert browser._context_id is browser._user_context is None
    else:
        assert len(browser._ws.commands) == 1


def test_chrome_leaves_the_shared_tab_blank(monkeypatch):
    monkeypatch.setattr(chrome_cdp, "find_chrome", lambda executable: "c")
    browser = chrome_cdp.ChromeCDP(isolate_pages=False)
    browser._session_id = "tab"
    browser._ws = FakeConnection({})

    browser._leave_page()

    # Sent to the page, so that it stops running.
    [command] = browser._ws.commands
    assert command["method"] == "Page.navigate"
    assert command["params"] == {"url": "about:blank"}
    assert command["sessionId"] == "tab"


def test_firefox_closes_the_windows_that_the_page_opened(monkeypatch):
    monkeypatch.setattr(firefox_bidi, "find_firefox", lambda executable: "f")
    browser = firefox_bidi.FirefoxBiDi(isolate_pages=False)
    browser._context_id = "tab"
    contexts = [
        # Opened by a window that the page opened.
        {"context": "second popup", "originalOpener": "popup"},
        {"context": "tab", "originalOpener": None, "children": [
            {"context": "frame", "originalOpener": None, "children": []},
        ]},
        {"context": "popup", "originalOpener": "tab", "children": []},
        {"context": "popup of the frame", "originalOpener": "frame"},
        # Another window of `max_concurrency`, and the window that its page
        # opened.
        {"context": "window", "originalOpener": None, "children": []},
        {"context": "popup of the window", "originalOpener": "window"},
    ]
    browser._ws = FakeConnection({
        "browsingContext.getTree": {"result": {"contexts": contexts}},
    })

    browser._leave_page()

    closed = [
        command["params"]["context"] for command in browser._ws.commands
        if command["method"] == "browsingContext.close"
    ]
    assert sorted(closed) == ["popup", "popup of the frame", "second popup"]


@pytest.mark.parametrize("shown, url, reloaded", [
    # Another anchor of the page that the tab shows, or the same one.
    ("http://h/page#a", "http://h/page#b", True),
    ("http://h/page#a", "http://h/page#a", True),
    ("http://h/page", "http://h/page#b", True),
    # Another page.
    ("http://h/other", "http://h/page#b", False),
    ("http://h/page", "http://h/page", False),
])
def test_firefox_loads_another_anchor_again(monkeypatch, shown, url, reloaded):
    monkeypatch.setattr(firefox_bidi, "find_firefox", lambda executable: "f")
    browser = firefox_bidi.FirefoxBiDi(isolate_pages=False)
    browser._context_id = "tab"
    browser._ws = FakeConnection({
        "browsingContext.getTree": {"result": {"contexts": [
            {"context": "tab", "url": shown},
        ]}},
        "browsingContext.navigate": {"result": {"url": url}},
        "browsingContext.reload": {"result": {"url": url}},
    })

    browser._navigate(url)

    commands = browser._ws.commands
    # The page that the tab shows is only asked for a URL with an anchor.
    expected = ["browsingContext.getTree"] if "#" in url else []
    expected.append("browsingContext.navigate")
    if reloaded:
        expected.append("browsingContext.reload")
        assert commands[-1]["params"] == {"context": "tab", "wait": "complete"}
    assert [command["method"] for command in commands] == expected


def test_firefox_draws_no_link_as_visited(monkeypatch, tmp_path):
    monkeypatch.setattr(firefox_bidi, "find_firefox", lambda executable: "f")

    firefox_bidi.FirefoxBiDi()._write_profile_prefs(str(tmp_path))

    # Its private contexts share its history.
    prefs = (tmp_path / "user.js").read_text(encoding="utf-8")
    assert 'user_pref("places.history.enabled", false);' in prefs


# With a browser. Each test starts its own, and skips if it is not found.

BROWSERS = ["chrome", "firefox", "edge"]


def _real_hti(browser, tmp_path, **options):
    try:
        return Html2Image(
            browser=browser,
            output_path=str(tmp_path / "output"),
            temp_path=str(tmp_path / "temp"),
            size=(200, 100),
            disable_logging=True,
            **options,
        )
    except FileNotFoundError:
        pytest.skip(f"'{browser}' executable not found on this machine")


@pytest.mark.parametrize("isolate_pages", [True, False])
@pytest.mark.parametrize("browser", BROWSERS)
def test_pages_of_a_list(browser, isolate_pages, tmp_path, serve):
    hti = _real_hti(browser, tmp_path, isolate_pages=isolate_pages)

    # Three pages: the browser will keep a page after the second one.
    paths = hti.screenshot(
        url=[serve(LEAVE_STATE), serve(SHOW_STATE), serve(SHOW_STATE)],
        save_as=["leave.png", "show.png", "show_again.png"],
    )

    for path in paths[1:]:
        assert found_state(path) == dict.fromkeys(STATES, not isolate_pages)


@pytest.mark.parametrize("isolate_pages", [True, False])
@pytest.mark.parametrize("browser", BROWSERS)
def test_pages_of_a_with_block(browser, isolate_pages, tmp_path, serve):
    hti = _real_hti(browser, tmp_path, isolate_pages=isolate_pages)

    with hti:
        hti.screenshot(url=serve(LEAVE_STATE), save_as="leave.png")
        paths = [
            hti.screenshot(url=serve(SHOW_STATE), save_as=name)[0]
            for name in ("show.png", "show_again.png")
        ]

    for path in paths:
        assert found_state(path) == dict.fromkeys(STATES, not isolate_pages)


@pytest.mark.parametrize("isolate_pages", [True, False])
@pytest.mark.parametrize("browser", BROWSERS)
def test_pages_of_windows(browser, isolate_pages, tmp_path, serve):
    hti = _real_hti(
        browser, tmp_path, isolate_pages=isolate_pages, max_concurrency=3
    )

    with hti:
        with ThreadPoolExecutor(3) as executor:
            list(executor.map(
                lambda index: hti.screenshot(
                    url=serve(LEAVE_STATE), save_as=f"leave_{index}.png"
                ),
                range(3),
            ))
        [path] = hti.screenshot(url=serve(SHOW_STATE), save_as="show.png")

    found = found_state(path)
    if isolate_pages:
        assert found == dict.fromkeys(STATES, False)
    else:
        # The windows share the cookies and the local storage. The session
        # storage and the name belong to a window.
        assert found["cookie"] and found["local storage"]


@pytest.mark.parametrize("browser", ["chrome", "firefox"])
def test_browser_without_private_pages(
    browser, tmp_path, serve, monkeypatch
):
    hti = _real_hti(browser, tmp_path)
    monkeypatch.setattr(
        hti.browser, "_open_private_page", lambda **options: False
    )

    # As with Firefox before version 124, the browser is started again for
    # each page.
    paths = hti.screenshot(
        url=[serve(LEAVE_STATE), serve(SHOW_STATE)],
        save_as=["leave.png", "show.png"],
    )

    assert found_state(paths[1]) == dict.fromkeys(STATES, False)
    assert hti.browser._ws is None


@pytest.mark.parametrize("browser", ["chrome", "firefox"])
def test_windows_without_private_pages(browser, tmp_path, serve, monkeypatch):
    hti = _real_hti(browser, tmp_path, max_concurrency=2)
    # The windows are copies of the browser, made in the `with` block.
    monkeypatch.setattr(
        hti.browser, "_open_private_page", lambda **options: False
    )

    # As with Firefox before version 124, a window cannot start the browser
    # again for each page, since the other windows use it.
    with hti:
        with pytest.raises(BrowserError, match="Firefox 124 or later"):
            hti.screenshot(url=serve(SHOW_STATE), save_as="show.png")
        assert not os.path.exists(os.path.join(hti.output_path, "show.png"))


@pytest.mark.parametrize("browser", BROWSERS)
def test_download_in_a_private_window_is_refused(
    browser, tmp_path, download_url
):
    hti = _real_hti(browser, tmp_path, max_concurrency=3)

    # With Firefox, the window gets the download event of its new page
    # through the connection that the windows share.
    with hti:
        with ThreadPoolExecutor(3) as executor:
            calls = [
                executor.submit(
                    hti.screenshot, url=download_url, save_as=f"{index}.png"
                )
                for index in range(3)
            ]
            for call in calls:
                with pytest.raises(PageLoadError):
                    call.result()
        time.sleep(1)


@pytest.mark.parametrize("browser", ["chrome", "edge"])
def test_download_in_a_private_page_is_refused(
    browser, tmp_path, download_url
):
    hti = _real_hti(browser, tmp_path)

    with hti:
        with pytest.raises(PageLoadError):
            hti.screenshot(url=download_url, save_as="download.png")
        # Leaves the browser the time to save the downloaded file, if it
        # does, before it is closed.
        time.sleep(1)


def _color(path):
    return Image.open(path).convert("RGB").getpixel((10, 10))


# Takes half a second to load, so that the pages captured at the same time
# each take a window of their own.
SLOW = "<script>const end = Date.now() + 500; while (Date.now() < end) {}"

# Opens two windows, one of them without access to the page, and will show
# an alert 1.5 seconds after it loaded: after its screenshot, even on a slow
# machine.
ACTING_PAGE = (
    _page_of_color(RED) + SLOW + "; onload = () => {"
    " window.open('about:blank', '_blank', 'width=200,height=200');"
    " window.open('about:blank', '_blank', 'noopener');"
    " setTimeout(() => alert('still there'), 1500) }</script>"
)


@pytest.mark.parametrize("isolate_pages", [True, False])
@pytest.mark.parametrize("browser", BROWSERS)
def test_pages_that_act_after_their_screenshot(
    browser, isolate_pages, tmp_path
):
    hti = _real_hti(
        browser, tmp_path, isolate_pages=isolate_pages, max_concurrency=3
    )

    def capture_three(html, prefix):
        with ThreadPoolExecutor(3) as executor:
            return list(executor.map(
                lambda index: hti.screenshot(
                    html_str=html, save_as=f"{prefix}_{index}.png"
                )[0],
                range(3),
            ))

    with hti:
        capture_three(ACTING_PAGE, "acting")
        # The alerts would show while no page is captured. With Chrome and
        # Edge, an alert blocked the next screenshot of its window.
        time.sleep(3)
        paths = capture_three(
            _page_of_color(BLUE) + SLOW + "</script>", "next"
        )
        # Only the windows of `max_concurrency` are left. Chrome and Edge do
        # not open a window without a gesture of the user.
        assert len(_pages(hti)) == 3

    assert [_color(path) for path in paths] == [BLUE] * 3


@pytest.mark.parametrize("isolate_pages", [True, False])
@pytest.mark.parametrize("browser", BROWSERS)
def test_anchors_of_a_page_that_changed(browser, isolate_pages, tmp_path):
    hti = _real_hti(browser, tmp_path, isolate_pages=isolate_pages)
    page = tmp_path / "anchors.html"

    with hti:
        for anchor, color in [("#a", RED), ("#b", GREEN), ("#b", BLUE)]:
            # In the same tab, the page would not be loaded again.
            page.write_text(
                _page_of_color(color) + '<div id="a"></div><div id="b"></div>'
            )
            [path] = hti.screenshot(
                url=page.as_uri() + anchor, save_as="anchor.png"
            )
            assert _color(path) == color


# Lengths without unit, which only a page without doctype accepts.
UNITLESS = "div { width: 100; height: 50; background: rgb(255, 0, 0) }"


def _red_pixels(path):
    colors = Image.open(path).convert("RGB").getcolors(1 << 16)
    return sum(count for count, color in colors if color == RED)


# Since version 140, Firefox shares the same <style> sheet between two pages
# of the same origin, even if one of them has a doctype and the other not.
@pytest.mark.parametrize("isolate_pages", [True, False])
def test_firefox_style_sheet_of_a_page_from_the_same_file(
    isolate_pages, tmp_path
):
    hti = _real_hti("firefox", tmp_path, isolate_pages=isolate_pages)
    files = []
    for doctype in ("<!DOCTYPE html>", ""):
        page = tmp_path / str(len(files)) / "page.html"
        page.parent.mkdir()
        page.write_text(f"{doctype}<style>{UNITLESS}</style><div></div>")
        files.append(str(page))

    with hti:
        # Two calls with the same `save_as`, then two files of the same name.
        reds = []
        for doctype in (True, False):
            hti.add_doctype = doctype
            [path] = hti.screenshot(
                html_str="<div></div>", css_str=UNITLESS, save_as="page.png"
            )
            reds.append(_red_pixels(path))
        paths = hti.screenshot(html_file=files, save_as=["a.png", "b.png"])
        reds += [_red_pixels(path) for path in paths]

    assert reds == [0, 5000] * 2
