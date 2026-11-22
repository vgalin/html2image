"""Fixtures shared by the tests.

The tests that load a URL use local servers, so that none of them needs
the network.
"""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import threading


@contextmanager
def _local_server(handler):
    """Runs a local HTTP server in a thread, and yields its base URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
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
