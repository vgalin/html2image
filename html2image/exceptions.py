"""Exceptions raised by html2image.

BrowserNotFoundError is also a FileNotFoundError, as in html2image 2.x,
so existing `except FileNotFoundError` clauses keep working. The two
timeout errors are also TimeoutError.
"""


class Html2ImageError(Exception):
    """Base class of the exceptions raised by html2image."""


class BrowserNotFoundError(Html2ImageError, FileNotFoundError):
    """No usable browser executable was found."""


class BrowserError(Html2ImageError):
    """The browser could not start, reported an error or was lost."""


class BrowserTimeoutError(BrowserError, TimeoutError):
    """The browser did not answer in time."""


class PageLoadError(Html2ImageError):
    """The page could not be loaded, but the browser is fine."""


class PageLoadTimeoutError(PageLoadError, TimeoutError):
    """The page did not finish loading in time."""
