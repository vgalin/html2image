from abc import ABC, abstractmethod
import contextlib
import json
import logging
import os
import shutil
import threading
import time

from websocket import WebSocketException

from ..exceptions import (
    BrowserError,
    CaptureTooLargeError,
    FullPageWarning,
    PageLoadError,
    PageLoadTimeoutError,
)

logger = logging.getLogger(__name__)

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


def remove_profile(path, timeout=5):
    """Delete the profile directory of a browser that was just closed.

    On Windows, a file cannot be deleted while a process has it open, and
    the browser may still be exiting. The deletion will be tried again until
    `timeout` seconds have passed. After that, the files that are still
    open will be left on the disk.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            shutil.rmtree(path)
            return
        except OSError:
            if not os.path.exists(path):
                return
            time.sleep(0.1)
    shutil.rmtree(path, ignore_errors=True)


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


class ConcurrentBrowser(Browser):
    """A web browser that can take `max_concurrency` screenshots at the same
    time, from several threads, each in a window of its own.

    The browser class connects to the browser with `_connect_ws()`, which
    starts it if needed, and opens and closes a window with `_open_window()`
    and `_close_window()`.
    """

    def _init_windows(self, max_concurrency):
        """Check `max_concurrency` and create the locks, see `_window()`."""
        if not isinstance(max_concurrency, int) or max_concurrency < 1:
            raise ValueError(
                'max_concurrency should be 1 or more, '
                f'got {max_concurrency!r}.'
            )
        self.max_concurrency = max_concurrency
        # At most `max_concurrency` captures at once, and, with more than one,
        # the windows that are not in use, see `_window()`.
        self._slots = threading.Semaphore(max_concurrency)
        self._windows = None
        # Held while the browser starts or stops, and while a window is
        # taken.
        self._lock = threading.RLock()

    def __getstate__(self):
        """Return the attributes to copy or pickle, without the locks,
        which cannot be copied. The copy will get its own.
        """
        state = self.__dict__.copy()
        del state['_slots'], state['_lock']
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._slots = threading.Semaphore(self.max_concurrency)
        self._lock = threading.RLock()

    @contextlib.contextmanager
    def _window(self):
        """Yield the object that will load and capture a page, see
        `screenshot()`.

        With `max_concurrency=1`, or if the browser was not started with
        `with`, it is this object, and the calls will run one after the
        other, as before. Otherwise, it is a window that no other call is
        using.
        """
        with self._slots:
            with self._lock:
                windows = self._windows
                if windows is None:
                    auto_started = self._ws is None
                    try:
                        if auto_started:
                            # The browser will only be started for this
                            # call, without the other windows.
                            self._connect_ws()
                        yield self
                    except Exception as error:
                        if not auto_started and needs_restart(error):
                            self.__exit__()
                            self.__enter__()
                        raise
                    finally:
                        if auto_started:
                            self.__exit__()
                    return
                window = windows.pop()

            try:
                yield window
            except Exception as error:
                if needs_restart(error):
                    window = self._replace_window(windows, window)
                raise
            finally:
                with self._lock:
                    if windows is self._windows:
                        windows.append(window)
                    else:
                        # The browser was closed or restarted during the
                        # capture.
                        window._ws.close()

    def _replace_window(self, windows, window):
        """Return the window that will replace `window`, after an error that
        may have left it unusable.

        If the browser still answers, only the window will be replaced. If
        not, the browser will be restarted, unless it was already closed or
        restarted during the capture.
        """
        with self._lock:
            if windows is not self._windows:
                return window
            if self._close_window(window):
                window._ws.close()
                try:
                    return self._open_window()
                except BrowserError:
                    logger.debug('Could not open a window.', exc_info=True)
            self.__exit__()
            self.__enter__()
            return window


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
