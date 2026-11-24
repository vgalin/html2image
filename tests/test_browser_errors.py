"""Tests of what the browsers do when a screenshot fails.

Most tests use fake connections. The tests that start a browser skip if it
is not found on the current machine, and only open local pages.
"""

from html2image import (
    Html2Image,
    BrowserError,
    BrowserTimeoutError,
    CaptureTooLargeError,
    FullPageWarning,
    PageLoadError,
    PageLoadTimeoutError,
)
from html2image.browsers import chrome_cdp, firefox_bidi
from html2image.browsers.browser import needs_restart, remove_profile
from PIL import Image
from websocket import (
    WebSocketConnectionClosedException,
    WebSocketTimeoutException,
)

import base64
import json
import os
import pytest
import shutil
import signal
import socket
import subprocess
import time

BROWSERS = ["chrome", "edge", "firefox"]

LOST_CONNECTION_ERRORS = [
    ConnectionResetError(10054, "An existing connection was forcibly closed"),
    BrokenPipeError(32, "Broken pipe"),
    ConnectionAbortedError(10053, "An established connection was aborted"),
    WebSocketConnectionClosedException("Connection to remote host was lost."),
]


class FakeWebSocket:
    """Replays messages, then times out like an idle connection.

    The messages given as text are replayed as they are. `send_error` and
    `recv_error` are raised instead, if given.
    """

    def __init__(self, messages=(), send_error=None, recv_error=None):
        self.messages = [
            message if isinstance(message, str) else json.dumps(message)
            for message in messages
        ]
        self.send_error = send_error
        self.recv_error = recv_error

    def send(self, payload):
        if self.send_error:
            raise self.send_error

    def settimeout(self, timeout):
        pass

    def recv(self):
        if self.recv_error:
            raise self.recv_error
        if not self.messages:
            raise WebSocketTimeoutException()
        return self.messages.pop(0)


class FakeChrome(FakeWebSocket):
    """Answers each CDP command, as Chrome would for a page that loads.

    `navigations` are the answers to the Page.navigate commands, in order.
    """

    def __init__(self, navigations=()):
        super().__init__()
        self.navigations = list(navigations)
        self.methods = []

    def send(self, payload):
        command = json.loads(payload)
        self.methods.append(command["method"])
        answer = {"id": command["id"], "result": {}}
        if command["method"] == "Page.navigate":
            answer = {"id": command["id"], **self.navigations.pop(0)}
        elif command["method"] == "Page.captureScreenshot":
            answer["result"]["data"] = base64.b64encode(b"image").decode()
        self.messages.append(json.dumps(answer))

        loader_id = answer.get("result", {}).get("loaderId")
        if loader_id:
            self.messages.append(json.dumps({
                "method": "Page.lifecycleEvent",
                "params": {"frameId": "main", "loaderId": loader_id, "name": "load"},
            }))


LOADED = {"result": {"frameId": "main", "loaderId": "page"}}


def _failed(error_text):
    return {"result": {"frameId": "main", "loaderId": "page", "errorText": error_text}}


@pytest.fixture
def cdp_browser(monkeypatch):
    monkeypatch.setattr(chrome_cdp, "find_chrome", lambda executable: "chrome")
    return chrome_cdp.ChromeCDP()


@pytest.fixture
def bidi_browser(monkeypatch):
    monkeypatch.setattr(
        firefox_bidi, "find_firefox", lambda executable: "firefox"
    )
    browser = firefox_bidi.FirefoxBiDi()
    browser._context_id = "context"
    return browser


@pytest.fixture
def restarts(monkeypatch, cdp_browser, bidi_browser):
    """Counts the restarts of the fake browsers, which are both started."""
    count = []
    for browser in (cdp_browser, bidi_browser):
        browser._ws = FakeWebSocket()
        monkeypatch.setattr(browser, "__exit__", lambda *exc: count.append("exit"))
        monkeypatch.setattr(browser, "__enter__", lambda: count.append("enter"))
    return count


# Part A: the browser is only restarted when it may be unusable.

@pytest.mark.parametrize("error, restart", [
    (PageLoadError("Navigation failed: net::ERR_NAME_NOT_RESOLVED"), False),
    (PageLoadTimeoutError("Timed out"), True),
    (ValueError('"div[" is not a valid CSS selector.'), False),
    (CaptureTooLargeError("Too large"), False),
    (ImportError("pyvips is required"), False),
    (FullPageWarning("A seam could not be checked."), False),
    (BrowserError("CDP error -32000: Not allowed"), True),
    (BrowserTimeoutError("Timed out"), True),
    (BrowserError("The connection to the browser was lost."), True),
    (OSError(22, "Invalid argument"), True),
    (KeyError("result"), True),
])
def test_needs_restart(error, restart):
    assert needs_restart(error) is restart


@pytest.mark.parametrize("browser_name", ["cdp", "bidi"])
@pytest.mark.parametrize("error, restart", [
    (PageLoadError("Navigation failed"), False),
    (ValueError("Invalid selector"), False),
    (PageLoadTimeoutError("Timed out"), True),
    (BrowserError("Lost"), True),
])
def test_screenshot_restarts_only_if_needed(
    monkeypatch, restarts, cdp_browser, bidi_browser, tmp_path,
    browser_name, error, restart,
):
    browser = cdp_browser if browser_name == "cdp" else bidi_browser

    def fail(*args, **kwargs):
        raise error

    first_command = "cdp_send" if browser_name == "cdp" else "_set_viewport"
    monkeypatch.setattr(browser, first_command, fail)

    with pytest.raises(type(error)):
        browser.screenshot("http://127.0.0.1:1/", str(tmp_path))

    assert restarts == (["exit", "enter"] if restart else [])


@pytest.mark.parametrize("browser_name", ["cdp", "bidi"])
def test_malformed_url_does_not_reach_the_browser(
    restarts, cdp_browser, bidi_browser, tmp_path, browser_name,
):
    browser = cdp_browser if browser_name == "cdp" else bidi_browser
    browser._ws = FakeWebSocket(send_error=AssertionError("sent"))

    with pytest.raises(ValueError, match="Invalid IPv6 URL"):
        browser.screenshot("http://[malformed", str(tmp_path))

    assert restarts == []


def test_cdp_error_answer_to_navigation_is_page_load_error(
    restarts, cdp_browser, tmp_path,
):
    cdp_browser._ws = FakeChrome(navigations=[
        {"error": {"code": -32000, "message": "Cannot navigate to invalid URL"}},
    ])

    with pytest.raises(PageLoadError) as excinfo:
        cdp_browser.screenshot("example.com", str(tmp_path))

    assert str(excinfo.value) == "Navigation failed: Cannot navigate to invalid URL"
    assert restarts == []


def test_cdp_error_answer_to_another_command_is_browser_error(cdp_browser):
    cdp_browser._ws = FakeWebSocket([
        {"id": 2, "error": {"code": -32000, "message": "Not allowed"}},
    ])

    with pytest.raises(BrowserError, match="Not allowed"):
        cdp_browser._wait_for_navigation_complete(1, timeout=1)


def test_cdp_navigation_timeout_message(cdp_browser):
    cdp_browser._ws = FakeWebSocket()

    with pytest.raises(PageLoadTimeoutError) as excinfo:
        cdp_browser._wait_for_navigation_complete(1, timeout=0.2)

    assert str(excinfo.value) == (
        "Timed out after 0.2s waiting for page navigation."
    )


# Part B: a lost connection to the browser is a BrowserError.

@pytest.mark.parametrize("error", LOST_CONNECTION_ERRORS)
def test_cdp_lost_connection_while_receiving(cdp_browser, error):
    cdp_browser._ws = FakeWebSocket(recv_error=error)

    for wait in (
        lambda: cdp_browser._wait_for_result(1, timeout=1),
        lambda: cdp_browser._wait_for_navigation_complete(1, timeout=1),
    ):
        with pytest.raises(BrowserError) as excinfo:
            wait()

        assert type(excinfo.value) is BrowserError
        assert excinfo.value.__cause__ is error


@pytest.mark.parametrize("error", LOST_CONNECTION_ERRORS)
def test_cdp_lost_connection_while_sending(cdp_browser, error):
    cdp_browser._ws = FakeWebSocket(send_error=error)

    with pytest.raises(BrowserError) as excinfo:
        cdp_browser.cdp_send("Page.enable")

    assert excinfo.value.__cause__ is error


@pytest.mark.parametrize("error", LOST_CONNECTION_ERRORS)
def test_bidi_lost_connection(bidi_browser, error):
    for fake in (
        FakeWebSocket(recv_error=error),
        FakeWebSocket(send_error=error),
    ):
        bidi_browser._ws = fake
        for command in (bidi_browser._get_tree, lambda: bidi_browser._navigate("about:blank")):
            with pytest.raises(BrowserError) as excinfo:
                command()

            # Not a PageLoadError, which would keep the lost browser.
            assert type(excinfo.value) is BrowserError
            assert excinfo.value.__cause__ is error


# An empty message is what the WebSocket connection returns once the browser
# closed it.
UNREADABLE_MESSAGES = [
    ("", "The connection to the browser was lost."),
    ("not JSON", "Could not read a message from the browser."),
]


@pytest.mark.parametrize("raw, error", UNREADABLE_MESSAGES)
def test_cdp_unreadable_message_is_browser_error(cdp_browser, raw, error):
    cdp_browser._ws = FakeWebSocket([raw])

    with pytest.raises(BrowserError) as excinfo:
        cdp_browser._wait_for_result(1, timeout=1)

    assert type(excinfo.value) is BrowserError
    assert str(excinfo.value) == error


@pytest.mark.parametrize("raw, error", UNREADABLE_MESSAGES)
def test_bidi_unreadable_message_is_browser_error(bidi_browser, raw, error):
    for command in (bidi_browser._get_tree, lambda: bidi_browser._navigate("about:blank")):
        bidi_browser._ws = FakeWebSocket([raw])

        with pytest.raises(BrowserError) as excinfo:
            command()

        assert type(excinfo.value) is BrowserError
        assert str(excinfo.value) == error


@pytest.mark.parametrize("browser_name", ["cdp", "bidi"])
def test_screenshot_restarts_after_closed_connection(
    restarts, cdp_browser, bidi_browser, tmp_path, browser_name,
):
    browser = cdp_browser if browser_name == "cdp" else bidi_browser
    browser._ws = FakeWebSocket([""])

    with pytest.raises(BrowserError, match="connection to the browser was lost"):
        browser.screenshot("http://127.0.0.1:1/", str(tmp_path))

    assert restarts == ["exit", "enter"]


def test_cdp_browser_pid_unknown(cdp_browser):
    cdp_browser._ws = FakeWebSocket([
        {"id": 1, "result": {"processInfo": [{"type": "renderer", "id": 5}]}},
    ])

    assert cdp_browser._find_browser_pid() is None


def test_cdp_file_error_is_not_wrapped(cdp_browser, tmp_path):
    cdp_browser._ws = FakeChrome()

    with pytest.raises(FileNotFoundError):
        cdp_browser._capture(
            str(tmp_path / "missing_folder" / "page.png"),
            {"x": 0, "y": 0, "width": 10, "height": 10},
        )


# Part C: with Firefox, a URL that starts a download is a PageLoadError.

def _download_will_begin(context="context", navigation="requested"):
    return {
        "type": "event",
        "method": "browsingContext.downloadWillBegin",
        "params": {"context": context, "navigation": navigation},
    }


NAVIGATED = {"type": "success", "id": 1, "result": {
    "navigation": "requested", "url": "file:///previous.html",
}}
STATUS = {"type": "success", "id": 2, "result": {"ready": False}}


@pytest.mark.parametrize("messages", [
    [_download_will_begin(), NAVIGATED, STATUS],
    # Firefox can report the download after its answer, with another
    # navigation ID.
    [NAVIGATED, _download_will_begin(navigation="other"), STATUS],
])
def test_bidi_download_is_page_load_error(bidi_browser, messages):
    bidi_browser._downloads_reported = True
    bidi_browser._ws = FakeWebSocket(messages)

    with pytest.raises(PageLoadError, match="started a download"):
        bidi_browser._navigate("http://127.0.0.1:1/file")


def test_bidi_download_in_another_context_is_ignored(bidi_browser):
    bidi_browser._downloads_reported = True
    bidi_browser._ws = FakeWebSocket([
        _download_will_begin(context="frame"), NAVIGATED, STATUS,
    ])

    bidi_browser._navigate("http://127.0.0.1:1/")


class FakeFirefoxProcess:
    """A Firefox process that does not exit by itself, or that exited with
    `returncode`."""

    def __init__(self, returncode=None):
        self.waits = []
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.waits.append(timeout)
        raise subprocess.TimeoutExpired("firefox", timeout)


@pytest.mark.parametrize("fake, waits", [
    # Firefox 116 and older do not know browser.close.
    (FakeWebSocket([{
        "type": "error", "id": 1, "error": "unknown command",
        "message": "browser.close",
    }]), []),
    # Firefox was lost.
    (FakeWebSocket([""]), []),
    (FakeWebSocket(recv_error=LOST_CONNECTION_ERRORS[0]), []),
    (FakeWebSocket(send_error=LOST_CONNECTION_ERRORS[1]), []),
    # Firefox accepted, but did not exit in time.
    (FakeWebSocket([{"type": "success", "id": 1, "result": {}}]), [5]),
], ids=["refused", "closed", "reset", "broken pipe", "accepted"])
def test_firefox_is_stopped_if_it_does_not_close(
    monkeypatch, bidi_browser, fake, waits,
):
    process = FakeFirefoxProcess()
    bidi_browser._ws = fake
    bidi_browser.proc = process
    stopped = []
    monkeypatch.setattr(
        bidi_browser, "_shutdown_process_tree", lambda: stopped.append(True)
    )

    bidi_browser.__exit__()

    assert stopped == [True]
    assert process.waits == waits
    assert bidi_browser._ws is None
    assert bidi_browser.proc is None


@pytest.mark.parametrize("fixture, attribute", [
    ("cdp_browser", "_user_data_dir"),
    ("bidi_browser", "_profile_dir"),
])
@pytest.mark.parametrize("error", [
    PermissionError(13, "The file is used by a process"),
    # The browser deleted one of its files while it was exiting.
    FileNotFoundError(2, "The file was deleted"),
], ids=["open file", "deleted file"])
def test_profile_is_removed_once_its_files_are_closed(
    monkeypatch, request, tmp_path, fixture, attribute, error,
):
    browser = request.getfixturevalue(fixture)
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "cache").write_text("cache")
    setattr(browser, attribute, str(profile_dir))
    # On Windows, the processes of a closed browser can keep files of the
    # profile open for a moment, while they exit.
    rmtree = shutil.rmtree
    attempts = []

    def locked_rmtree(path, ignore_errors=False):
        attempts.append(path)
        if len(attempts) < 3:
            if not ignore_errors:
                raise error
            return
        rmtree(path)

    monkeypatch.setattr(shutil, "rmtree", locked_rmtree)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    browser.__exit__()

    assert not profile_dir.exists()
    assert getattr(browser, attribute) is None


def test_profile_files_that_stay_open_are_left(monkeypatch, tmp_path):
    attempts = []

    def locked_rmtree(path, ignore_errors=False):
        attempts.append(ignore_errors)
        if not ignore_errors:
            raise PermissionError(13, "The file is used by a process")

    monkeypatch.setattr(shutil, "rmtree", locked_rmtree)

    remove_profile(str(tmp_path), timeout=0.3)

    # A last pass still deletes the files that are not open.
    assert attempts[0] is False
    assert attempts[-1] is True


def test_firefox_downloads_go_in_the_profile(tmp_path, bidi_browser):
    bidi_browser._write_profile_prefs(str(tmp_path))

    prefs = (tmp_path / "user.js").read_text(encoding="utf-8")
    download_dir = json.dumps(str(tmp_path / "downloads"))
    assert 'user_pref("browser.download.folderList", 2);' in prefs
    assert f'user_pref("browser.download.dir", {download_dir});' in prefs


# Part D: net::ERR_CERT_VERIFIER_CHANGED, with which Chrome asks to retry.

@pytest.mark.parametrize("navigations, error", [
    ([_failed("net::ERR_CERT_VERIFIER_CHANGED"), LOADED], None),
    (
        [_failed("net::ERR_CERT_VERIFIER_CHANGED")] * 2,
        "Navigation failed: net::ERR_CERT_VERIFIER_CHANGED",
    ),
    (
        [_failed("net::ERR_NAME_NOT_RESOLVED")],
        "Navigation failed: net::ERR_NAME_NOT_RESOLVED",
    ),
])
def test_cdp_retries_once_after_cert_verifier_changed(
    restarts, cdp_browser, tmp_path, navigations, error,
):
    fake_chrome = FakeChrome(navigations)
    cdp_browser._ws = fake_chrome

    if error:
        with pytest.raises(PageLoadError) as excinfo:
            cdp_browser.screenshot("https://example.com/", str(tmp_path))
        assert str(excinfo.value) == error
    else:
        cdp_browser.screenshot("https://example.com/", str(tmp_path))
        assert (tmp_path / "screenshot.png").read_bytes() == b"image"

    assert fake_chrome.methods.count("Page.navigate") == len(navigations)
    assert restarts == []


# Part E: html2image connects to Firefox while it starts, then asks it once
# for a session.

class FakeFirefox(FakeWebSocket):
    """Answers each BiDi command as a started Firefox would.

    The commands in `errors` are answered with that error. Those in
    `unanswered` are not answered, as if Firefox were too slow.
    """

    RESULTS = {
        "session.new": {"sessionId": "session"},
        "browsingContext.getTree": {"contexts": [{"context": "tab"}]},
    }

    def __init__(self, errors=None, unanswered=()):
        super().__init__()
        self.errors = errors or {}
        self.unanswered = unanswered
        self.methods = []

    def send(self, payload):
        command = json.loads(payload)
        method = command["method"]
        self.methods.append(method)
        if method in self.unanswered:
            return
        if method in self.errors:
            answer = {"type": "error", "error": self.errors[method]}
        else:
            result = self.RESULTS.get(method, {})
            answer = {"type": "success", "result": result}
        self.messages.append(json.dumps({"id": command["id"], **answer}))


def _fake_start(monkeypatch, browser, outcomes, returncode=None):
    """Makes `browser` start a fake Firefox, which exited with `returncode`
    if it is given. Each connection will raise or return the next of
    `outcomes`.

    Returns the options of each connection.
    """
    options = []

    def start_firefox():
        browser.proc = FakeFirefoxProcess(returncode)
        browser._current_port = 1

    def create_connection(url, **kwargs):
        options.append(kwargs)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(browser, "_start_firefox", start_firefox)
    monkeypatch.setattr(firefox_bidi, "create_connection", create_connection)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    return options


def _refused():
    return ConnectionRefusedError(10061, "No connection could be made")


def test_firefox_is_connected_to_once_it_listens(monkeypatch, bidi_browser):
    firefox = FakeFirefox()
    options = _fake_start(
        monkeypatch, bidi_browser, [_refused(), _refused(), firefox]
    )

    bidi_browser._connect_ws()

    # Firefox refuses an Origin header, and never answers with a
    # subprotocol, which websocket-client would then require.
    assert options == [{"timeout": 10, "suppress_origin": True}] * 3
    assert firefox.methods == [
        "session.status", "session.new", "session.subscribe",
        "browsingContext.getTree",
    ]
    assert bidi_browser._session_id == "session"
    assert bidi_browser._context_id == "tab"


@pytest.mark.parametrize("firefox_options, error, message", [
    # Firefox keeps the session that it was too slow to open, and would
    # refuse a new one.
    (dict(unanswered={"session.new"}), BrowserTimeoutError, "Timed out"),
    (
        dict(errors={"session.new": "session not created"}),
        BrowserError, "session not created",
    ),
], ids=["too slow", "refused"])
def test_firefox_is_asked_once_for_a_session(
    monkeypatch, bidi_browser, firefox_options, error, message,
):
    options = _fake_start(
        monkeypatch, bidi_browser,
        [FakeFirefox(**firefox_options), FakeFirefox()],
    )

    with pytest.raises(error, match=message):
        bidi_browser._connect_ws()

    assert len(options) == 1


def test_firefox_that_exited_is_not_waited_for(monkeypatch, bidi_browser):
    refused = _refused()
    # Firefox exits with code 69 when its port is already taken.
    options = _fake_start(monkeypatch, bidi_browser, [refused], returncode=69)

    with pytest.raises(BrowserError, match="exited with code 69") as excinfo:
        bidi_browser._connect_ws()

    assert len(options) == 1
    assert excinfo.value.__cause__ is refused


def test_firefox_connection_error_is_kept(monkeypatch, bidi_browser):
    errors = [_refused() for _ in range(40)]
    _fake_start(monkeypatch, bidi_browser, list(errors))

    with pytest.raises(BrowserError, match="after 40 attempts") as excinfo:
        bidi_browser._connect_ws()

    assert excinfo.value.__cause__ is errors[-1]


# With a browser.

def _make_hti(browser, tmp_path):
    try:
        return Html2Image(
            browser=browser,
            output_path=str(tmp_path),
            size=(320, 240),
            disable_logging=True,
        )
    except FileNotFoundError:
        pytest.skip(f"'{browser}' executable not found on this machine")


def _browser_pid(hti):
    """Returns the process ID of the browser of `hti`."""
    if isinstance(hti.browser, chrome_cdp.ChromeCDP):
        return hti.browser._browser_pid
    return hti.browser.proc.pid


def _assert_screenshot_works(hti):
    [path] = hti.screenshot(
        html_str='<body style="margin:0;background:blue"></body>',
        save_as="after.png",
    )
    assert Image.open(path).convert("RGB").getpixel((10, 10)) == (0, 0, 255)


@pytest.mark.parametrize("browser", BROWSERS)
def test_page_errors_keep_the_browser(tmp_path, browser, download_url):
    hti = _make_hti(browser, tmp_path)
    page = '<body><div id="card">card</div></body>'
    failures = [
        (PageLoadError, dict(url=download_url)),
        (PageLoadError, dict(url="example.com")),
        (ValueError, dict(url="http://[malformed")),
        (ValueError, dict(html_str=page, selector="div[")),
        (PageLoadError, dict(url="example.com", full_page=True)),
        (CaptureTooLargeError, dict(
            html_str=page, full_page=True, full_page_max_pixels=1000,
        )),
    ]

    with hti:
        pid = _browser_pid(hti)

        for error_class, options in failures:
            with pytest.raises(error_class):
                hti.screenshot(save_as="failed.png", **options)

            assert _browser_pid(hti) == pid, options

        _assert_screenshot_works(hti)
        # Leaves the browser the time to save the downloaded file, if it
        # does, before it is closed.
        time.sleep(1)


def _kill(pid):
    os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))


@pytest.mark.parametrize("browser", BROWSERS)
def test_lost_browser_is_restarted_once(tmp_path, browser):
    hti = _make_hti(browser, tmp_path)

    with hti:
        pid = _browser_pid(hti)
        _kill(pid)
        assert _port_is_closed(hti.browser._current_port)

        with pytest.raises(BrowserError) as excinfo:
            hti.screenshot(html_str="<p>lost</p>", save_as="lost.png")

        # The error of the system is kept. Its type depends on the system.
        assert excinfo.value.__cause__ is not None
        new_pid = _browser_pid(hti)
        assert new_pid != pid

        _assert_screenshot_works(hti)
        _assert_screenshot_works(hti)
        assert _browser_pid(hti) == new_pid


def _port_is_closed(port, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
        except OSError:
            return True
        time.sleep(0.2)
    return False


def test_firefox_closes_by_itself(monkeypatch, tmp_path):
    hti = _make_hti("firefox", tmp_path)

    with hti:
        _assert_screenshot_works(hti)
        browser = hti.browser
        process, profile_dir = browser.proc, browser._profile_dir
        # Records whether Firefox was still running when html2image was
        # about to stop it.
        running = []
        shutdown = browser._shutdown_process_tree

        def record_and_shutdown():
            running.append(process.poll() is None)
            shutdown()

        monkeypatch.setattr(
            browser, "_shutdown_process_tree", record_and_shutdown
        )

    assert running == [False]
    assert process.returncode == 0
    assert not os.path.exists(profile_dir)


@pytest.mark.parametrize("browser", ["chrome", "edge"])
def test_browser_that_does_not_close_is_killed(monkeypatch, tmp_path, browser):
    hti = _make_hti(browser, tmp_path)

    with hti:
        port = hti.browser._current_port
        profile_dir = hti.browser._user_data_dir
        # The browser is not asked to close, as if it took too long.
        send = hti.browser.cdp_send
        monkeypatch.setattr(
            hti.browser, "cdp_send",
            lambda method, **params: None if method == "Browser.close"
            else send(method, **params),
        )
        wait_for_close = hti.browser._wait_for_close
        monkeypatch.setattr(
            hti.browser, "_wait_for_close",
            lambda: wait_for_close(timeout=0.5),
        )

    assert _port_is_closed(port)
    assert not os.path.exists(profile_dir)


@pytest.mark.parametrize("browser", ["chrome", "edge"])
def test_profile_is_removed_after_closing(tmp_path, browser):
    hti = _make_hti(browser, tmp_path)

    with hti:
        _assert_screenshot_works(hti)
        profile_dir = hti.browser._user_data_dir

    assert not os.path.exists(profile_dir)
