from html2image import (
    Html2Image,
    Html2ImageError,
    BrowserNotFoundError,
    BrowserError,
    BrowserTimeoutError,
    PageLoadError,
    PageLoadTimeoutError,
)
from html2image.browsers import chrome_cdp, firefox_bidi
from websocket import WebSocketTimeoutException

import json
import pickle
import pytest
import socket

OUTPUT_PATH = "tests_output"

ERROR_CLASSES = [
    Html2ImageError,
    BrowserNotFoundError,
    BrowserError,
    BrowserTimeoutError,
    PageLoadError,
    PageLoadTimeoutError,
]

# The built-in exceptions that `except` clauses may use to catch them.
BUILT_IN_TYPES = {
    BrowserNotFoundError: [FileNotFoundError, OSError],
    BrowserTimeoutError: [TimeoutError, OSError],
    PageLoadTimeoutError: [TimeoutError, OSError],
}


@pytest.mark.parametrize("error_class, parents", [
    (Html2ImageError, [Exception]),
    (BrowserNotFoundError, [Html2ImageError, FileNotFoundError]),
    (BrowserError, [Html2ImageError]),
    (BrowserTimeoutError, [BrowserError, TimeoutError]),
    (PageLoadError, [Html2ImageError]),
    (PageLoadTimeoutError, [PageLoadError, TimeoutError]),
])
def test_exception_parents(error_class, parents):
    assert list(error_class.__bases__) == parents


@pytest.mark.parametrize("error_class, built_in_type", [
    (error_class, built_in_type)
    for error_class, built_in_types in BUILT_IN_TYPES.items()
    for built_in_type in built_in_types
])
def test_built_in_except_catches(error_class, built_in_type):
    with pytest.raises(built_in_type) as excinfo:
        raise error_class("message")

    assert isinstance(excinfo.value, Html2ImageError)
    assert str(excinfo.value) == "message"


def test_page_and_browser_errors_do_not_catch_each_other():
    assert not issubclass(PageLoadError, BrowserError)
    assert not issubclass(BrowserError, PageLoadError)


@pytest.mark.parametrize("error_class", ERROR_CLASSES)
def test_exception_survives_pickle(error_class):
    error = pickle.loads(pickle.dumps(error_class("message")))

    assert type(error) is error_class
    assert str(error) == "message"


@pytest.mark.parametrize("browser", [
    "chrome", "edge", "firefox",
    "chrome-headless", "edge-headless", "firefox-headless",
])
def test_missing_browser_executable(monkeypatch, tmp_path, browser):
    # The executable given in an environment variable would be used instead.
    monkeypatch.delenv("HTML2IMAGE_TOGGLE_ENV_VAR_LOOKUP", raising=False)

    with pytest.raises(BrowserNotFoundError, match="executable"):
        Html2Image(
            browser=browser,
            browser_executable=str(tmp_path / "missing_browser.exe"),
        )


@pytest.fixture
def closed_port_url():
    """URL of a local port on which nothing listens."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/"


@pytest.mark.parametrize("browser", ["chrome", "edge", "firefox"])
def test_unreachable_page_raises_page_load_error(browser, closed_port_url):
    try:
        hti = Html2Image(
            browser=browser, output_path=OUTPUT_PATH, disable_logging=True
        )
    except FileNotFoundError:
        pytest.skip(f"'{browser}' executable not found on this machine")

    with pytest.raises(PageLoadError, match="CONNECTION_REFUSED"):
        hti.screenshot(url=closed_port_url, save_as="unreachable.png")


class FakeWebSocket:
    """Replays messages, then times out like an idle connection."""

    def __init__(self, messages):
        self.messages = [json.dumps(message) for message in messages]

    def send(self, payload):
        pass

    def settimeout(self, timeout):
        pass

    def recv(self):
        if not self.messages:
            raise WebSocketTimeoutException()
        return self.messages.pop(0)


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


def test_cdp_response_timeout_is_browser_timeout(cdp_browser):
    cdp_browser._ws = FakeWebSocket([])

    with pytest.raises(BrowserTimeoutError):
        cdp_browser._wait_for_result(1, timeout=1)


def test_cdp_navigation_timeout_is_page_load_timeout(cdp_browser):
    cdp_browser._ws = FakeWebSocket([])

    with pytest.raises(PageLoadTimeoutError):
        cdp_browser._wait_for_navigation_complete(1, timeout=1)


def test_cdp_error_response_is_browser_error(cdp_browser):
    cdp_browser._ws = FakeWebSocket([
        {"id": 1, "error": {"code": -32000, "message": "Not allowed"}},
    ])

    with pytest.raises(BrowserError, match="CDP error -32000: Not allowed"):
        cdp_browser._wait_for_result(1, timeout=1)


def test_bidi_navigation_error_is_page_load_error(bidi_browser):
    error_message = {
        "id": 1, "type": "error",
        "error": "unknown error", "message": "NS_ERROR_CONNECTION_REFUSED",
    }
    bidi_browser._ws = FakeWebSocket([error_message])

    with pytest.raises(PageLoadError) as excinfo:
        bidi_browser._navigate("http://127.0.0.1:1/")

    assert not isinstance(excinfo.value, BrowserError)
    assert str(excinfo.value) == f"BiDi error for id=1: {error_message}"


def test_bidi_navigation_timeout_is_page_load_timeout(bidi_browser):
    bidi_browser._ws = FakeWebSocket([])

    with pytest.raises(PageLoadTimeoutError) as excinfo:
        bidi_browser._navigate("http://127.0.0.1:1/")

    assert not isinstance(excinfo.value, BrowserError)
    assert str(excinfo.value) == "Timed out after 30s waiting for BiDi message"


def test_bidi_error_outside_navigation_is_browser_error(bidi_browser):
    bidi_browser._ws = FakeWebSocket([{"id": 1, "type": "error"}])

    with pytest.raises(BrowserError):
        bidi_browser._get_tree()
