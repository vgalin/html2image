from abc import ABC, abstractmethod
import json

from websocket import WebSocketException

from ..exceptions import (
    BrowserError,
    CaptureTooLargeError,
    FullPageWarning,
    PageLoadError,
    PageLoadTimeoutError,
)

# The errors raised by the WebSocket connection to the browser when the
# browser is lost. They depend on the system and on when the browser
# stopped.
CONNECTION_ERRORS = (OSError, WebSocketException)

CONNECTION_LOST = 'The connection to the browser was lost.'


def read_message(raw):
    """Return the message `raw`, received from the browser, as a dict.

    The WebSocket connection returns an empty message when the browser
    closes it.
    """
    if not raw:
        raise BrowserError(CONNECTION_LOST)
    try:
        return json.loads(raw)
    except ValueError as error:
        raise BrowserError(
            'Could not read a message from the browser.'
        ) from error


def needs_restart(error):
    """Return True if the browser should be restarted after `error`.

    A failed screenshot can leave the browser unusable, for example with a
    navigation still pending. Only an error about the page or about the
    arguments leaves it as it was, as does a missing optional package or a
    warning turned into an error. A page that did not load in time may
    still be loading, so it is not one of them.
    """
    if isinstance(error, PageLoadTimeoutError):
        return True
    return not isinstance(error, (
        PageLoadError, CaptureTooLargeError, FullPageWarning, ValueError,
        ImportError,
    ))


class Browser(ABC):
    """Abstract class representing a web browser."""

    def __init__(self, flags, disable_logging):
        pass

    @property
    @abstractmethod
    def executable(self):
        pass

    @executable.setter
    @abstractmethod
    def executable(self, value):
        pass

    @abstractmethod
    def screenshot(self, *args, **kwargs):
        pass

    @abstractmethod
    def __enter__(self):
        pass

    @abstractmethod
    def __exit__(self, *exc):
        pass

    @property
    @abstractmethod
    def disable_logging(self):
        pass


class CDPBrowser(Browser):
    """A web browser that can be interacted with via Chrome DevTools Protocol.
    """

    def __init__(self, flags, cdp_port, disable_logging):
        pass


class BiDiBrowser(Browser):
    """A web browser that can be interacted with via WebDriver BiDi protocol.
    """

    def __init__(self, flags, bidi_port, disable_logging):
        pass
