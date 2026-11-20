"""Exceptions raised and warnings given by html2image.

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


class ElementNotFoundError(Html2ImageError):
    """An element given by a selector had nothing to capture.

    Either no element matched the selector, or the element was hidden,
    empty or outside of the page. The other images were saved anyway.

    Attributes:
        paths: the paths of the saved images, as `screenshot()` would
            have returned them.
        missing: the (selector, filename) pairs of the images that were
            not saved.
    """

    def __init__(self, message, paths=(), missing=()):
        super().__init__(message)
        self.paths = list(paths)
        self.missing = list(missing)


class CaptureTooLargeError(Html2ImageError):
    """An area was too large for the browser to capture in one go, or a
    page captured with `full_page=True` was larger than
    `full_page_max_pixels`.

    The other images were saved anyway.

    Attributes:
        paths: the paths of the saved images.
        too_large: the (selector, filename) pairs of the images that were
            not saved. The selector is None for a page captured with
            `full_page=True`.
    """

    def __init__(self, message, paths=(), too_large=()):
        super().__init__(message)
        self.paths = list(paths)
        self.too_large = list(too_large)


class FullPageWarning(UserWarning):
    """The image of a page captured with `full_page=True` was saved, but
    it may be wrong in places, for example because the page moved while
    it was captured, or it may stop before the end of the page.

    The message names the image and the places. The `warnings` module of
    Python can ignore this warning, or turn it into an error.
    """
