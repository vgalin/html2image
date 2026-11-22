"""Fixtures shared by the tests.

The tests that load a URL use local servers, so that none of them needs
the network.
"""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import os
import pytest
import socket
import sys
import threading
import uuid


class _Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # Browsers open connections that they close without a request.
        if not isinstance(sys.exc_info()[1], ConnectionError):
            super().handle_error(request, client_address)


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
