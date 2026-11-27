"""Fixtures shared by the tests.

The tests that load a URL use local servers, so that none of them needs
the network.

The tests that use `shared_browser` will share a browser with the other
tests of their module, instead of starting one for each screenshot.
"""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from html2image import Html2Image
from html2image.browsers.chrome_cdp import ChromeCDP

import os
import pytest
import socket
import sys
import threading
import uuid
import warnings


class _Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # Browsers open connections that they close without a request.
        if not isinstance(sys.exc_info()[1], ConnectionError):
            super().handle_error(request, client_address)


@pytest.fixture
def output_path(tmp_path):
    """A folder of its own for the images of a test, so that a test never
    reads an image left there by another one."""
    return str(tmp_path / "output")


@contextmanager
def _local_server(handler):
    """Runs a local HTTP server in a thread, and yields its base URL."""
    server = _Server(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def serve():
    """Serves pages from a local server: `serve(html)` returns the URL of a
    new page with this content."""
    pages = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = pages.get(self.path)
            if body is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with _local_server(Handler) as base_url:
        def add(html):
            path = f"/page_{len(pages)}.html"
            pages[path] = html.encode("utf-8")
            return base_url + path

        yield add


@pytest.fixture
def download_url():
    """URL of a local server that sends a file to download.

    The file has a unique name. If a browser saves it in the Downloads
    folder of the user, it is deleted, and the test fails.
    """
    filename = f"html2image_test_{uuid.uuid4().hex}.txt"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header(
                "Content-Disposition", f'attachment; filename="{filename}"'
            )
            self.send_header("Content-Length", "5")
            self.end_headers()
            self.wfile.write(b"hello")

        def log_message(self, *args):
            pass

    with _local_server(Handler) as base_url:
        yield base_url + "/file"

    downloaded = os.path.join(os.path.expanduser("~"), "Downloads", filename)
    if os.path.exists(downloaded):
        os.remove(downloaded)
        pytest.fail(f"The browser saved {downloaded}, which was deleted.")


@pytest.fixture
def unresponsive_url():
    """URL of a local server that accepts connections but never answers."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    yield f"http://127.0.0.1:{server.getsockname()[1]}/"
    server.close()


@pytest.fixture
def closed_port_url():
    """URL of a local port on which nothing listens."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/"


# The shared browser.

# With H2I_TEST_SHARED_BROWSER=0, each test will start its own browser, as
# if it did not share one. This tells whether a failure comes from the
# sharing.
SHARED = os.environ.get("H2I_TEST_SHARED_BROWSER") != "0"

# The options that Html2Image gives to the browser it creates. A test that
# needs one of them keeps its own browser.
LAUNCH_OPTIONS = {
    "browser_executable", "browser_cdp_port", "browser_bidi_port",
    "custom_flags", "allow_scripts_to_read_files", "max_concurrency",
}

# A browser that does not open a new page within this number of seconds
# will be started again.
NEW_PAGE_TIMEOUT = 10

# After this number of failed starts in a row, the next tests of the module
# will fail at once, instead of trying again.
MAX_FAILED_STARTS = 2

# The shared browsers of the module that is running, see `own_browser`.
_shared_browsers = []


class SharedHtml2Image(Html2Image):
    """Html2Image on a shared browser: `with` will leave it open."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


def _open_new_page(browser):
    """Open a new page in `browser`, and close its other pages.

    Each test will start from a page that no other test has touched. The
    local storage, the cookies and the cache are kept: a test that depends
    on them keeps its own browser. Raises an error if the browser does not
    answer in time.
    """
    if isinstance(browser, ChromeCDP):
        def send(method, **params):
            message_id = browser.cdp_send(method, **params)
            return browser._wait_for_result(
                message_id, timeout=NEW_PAGE_TIMEOUT
            )["result"]

        # Sent to the browser, not to its page.
        browser._session_id = None
        pages = [
            target["targetId"]
            for target in send("Target.getTargets")["targetInfos"]
            if target["type"] == "page"
        ]
        browser._target_id = send(
            "Target.createTarget", url="about:blank"
        )["targetId"]
        # From then on, the messages of the other pages will be ignored.
        browser._session_id = send(
            "Target.attachToTarget", targetId=browser._target_id, flatten=True
        )["sessionId"]
        for target_id in pages:
            send("Target.closeTarget", targetId=target_id)
    else:
        def send(method, **params):
            message_id = browser._bidi_send(method, **params)
            return browser._bidi_expect_ok(
                message_id, timeout=NEW_PAGE_TIMEOUT
            )["result"]

        pages = [
            context["context"]
            for context in send("browsingContext.getTree")["contexts"]
        ]
        browser._context_id = send(
            "browsingContext.create", type="tab"
        )["context"]
        for context in pages:
            send("browsingContext.close", context=context)


class SharedBrowser:
    """A browser kept open for the tests of a module, see `shared_browser`.

    It will be started again before a test if the previous test failed,
    closed it, or left it unable to open a new page. A warning will then
    tell it in the summary of pytest.
    """

    def __init__(self, name):
        self.name = name
        self.browser = None
        self.previous_test = None
        # Set by `pytest_runtest_makereport()`.
        self.test_failed = False
        self.failed_starts = 0
        self.start_error = None

    def make_hti(self, **options):
        """Return an Html2Image with `options`, which will take its
        screenshots in a new page of the shared browser.

        Skips the test if the browser is not installed.
        """
        assert not LAUNCH_OPTIONS & options.keys(), (
            "A test that gives the browser options keeps its own browser."
        )
        html2image_class = SharedHtml2Image if SHARED else Html2Image
        try:
            hti = html2image_class(
                browser=self.name, disable_logging=True, **options
            )
        except FileNotFoundError:
            pytest.skip(f"'{self.name}' executable not found on this machine")
        if SHARED:
            isolate_pages = hti.browser.isolate_pages
            hti.browser = self._ready_browser()
            hti.browser.isolate_pages = isolate_pages
        return hti

    def _ready_browser(self):
        """Return the browser, with a new page, started again if needed."""
        if self.browser is None:
            reason = None
        elif self.test_failed:
            reason = "the test failed"
        elif self.browser._ws is None:
            reason = "the browser was closed"
        else:
            try:
                _open_new_page(self.browser)
                return self.browser
            except Exception as error:
                reason = f"the browser did not open a new page ({error})"
        if reason:
            warnings.warn(
                f"The shared {self.name} was started again after "
                f"{self.previous_test}: {reason}."
            )
        self._start()
        return self.browser

    def _start(self):
        if self.failed_starts >= MAX_FAILED_STARTS:
            pytest.fail(
                f"The shared {self.name} did not start, "
                f"{self.failed_starts} times in a row: {self.start_error}",
                pytrace=False,
            )
        self.close()
        browser = Html2Image(browser=self.name, disable_logging=True).browser
        try:
            browser.__enter__()
        except Exception as error:
            self.failed_starts += 1
            self.start_error = f"{type(error).__name__}: {error}"
            raise
        self.browser = browser
        self.failed_starts = 0
        self.test_failed = False

    def close(self):
        browser, self.browser = self.browser, None
        if browser is not None:
            browser.__exit__()


@pytest.fixture(scope="module", params=["chrome", "firefox"])
def shared_browser(request):
    """A browser kept open for the tests of a module, with a new page for
    each test: `shared_browser.make_hti()` returns an Html2Image on it.

    The tests will run with Chrome and with Firefox. Edge runs the code of
    Chrome: a test also takes it with
    `@pytest.mark.parametrize("shared_browser", ["chrome", "firefox",
    "edge"], indirect=True)`. In a module, the browsers are always listed
    in this order, or a first part of it: pytest 8 groups the tests by the
    position of their browser in the list, pytest 9 by its name. All the
    tests of a browser will then run before the next browser starts, and
    only one shared browser will be open at a time.

    A test of the module that starts its own browser uses `own_browser`.
    """
    shared = SharedBrowser(request.param)
    _shared_browsers.append(shared)
    yield shared
    _shared_browsers.remove(shared)
    shared.close()


@pytest.fixture
def own_browser():
    """For a test that starts its own browser, in a module where the other
    tests share one: `@pytest.mark.usefixtures("own_browser")`.

    pytest can run this test while the shared browser of the tests before
    it is still open. This browser will be closed first, so that only one
    browser is open at a time. The next test that shares it will start it
    again.
    """
    for shared in _shared_browsers:
        shared.close()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item):
    """Tell the shared browser of a test whether the test failed."""
    report = yield
    shared = getattr(item, "funcargs", {}).get("shared_browser")
    if shared is not None:
        shared.test_failed = shared.test_failed or report.failed
        if report.when == "teardown":
            shared.previous_test = item.nodeid
    return report
