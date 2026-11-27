from .browser import (
    CONNECTION_ERRORS,
    CONNECTION_LOST,
    CDPBrowser,
    ConcurrentBrowser,
    read_message,
    remove_profile,
)
from ._page_fit_common import DEFAULT_MAX_PIXELS
from .search_utils import find_chrome
from . import _chromium_page_fit, _selector
from ..exceptions import (
    BrowserError,
    BrowserTimeoutError,
    PageLoadError,
    PageLoadTimeoutError,
)

import base64
import copy
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.parse import urlparse

import requests
from websocket import (
    WebSocketConnectionClosedException,
    WebSocketTimeoutException,
    create_connection,
)

logger = logging.getLogger(__name__)

# Default timeout (in seconds) for waiting on CDP responses
CDP_TIMEOUT = 30

TIMEOUT_ERRORS = (TimeoutError, socket.timeout, WebSocketTimeoutException)

# When its certificate verifier changes, Chrome stops using its open HTTP/2
# connections and fails their pending requests with this error. The page
# is then loaded once more, over a new connection.
CERT_VERIFIER_CHANGED = 'net::ERR_CERT_VERIFIER_CHANGED'

# Chrome only honors this flag along with its `--screenshot` flag, so the
# CDP backend reads its value and applies it through the protocol instead.
VIRTUAL_TIME_BUDGET_FLAG = '--virtual-time-budget='

# With several windows, on macOS, a page waited more than 30 seconds for
# Chrome to draw it. These flags keep Chrome from treating the pages of
# windows that are hidden or not in front as pages in the background.
WINDOW_FLAGS = [
    '--disable-backgrounding-occluded-windows',
    '--disable-renderer-backgrounding',
    '--disable-background-timer-throttling',
]

# On Windows, with a graphics card, Edge 158 drew pages with Skia Graphite,
# and some screenshots took more than ten times longer, up to 25 seconds
# for a full page of 20,000 pixels. This flag keeps Chrome and Edge on
# Skia Ganesh, the previous drawing engine, unless the user gives
# `--enable-skia-graphite`.
DISABLE_GRAPHITE_FLAG = '--disable-skia-graphite'

# Chrome draws a wrong image, without any error, when it captures an area
# larger than this number of pixels, in width or in height, in one go.
MAX_CAPTURE_SIZE = 16384


class ChromeCDP(CDPBrowser, ConcurrentBrowser):

    def __init__(
        self, executable=None, flags=None,
        print_command=False, cdp_port=None,
        disable_logging=False, allow_scripts_to_read_files=False,
        max_concurrency=1, isolate_pages=True,
    ):
        self._init_windows(max_concurrency, isolate_pages)
        self.executable = executable
        if not flags:
            self.flags = [
                '--hide-scrollbars',
            ]
        else:
            self.flags = [flags] if isinstance(flags, str) else flags

        self.print_command = print_command
        self.cdp_port = cdp_port
        self._disable_logging = disable_logging
        self.allow_scripts_to_read_files = allow_scripts_to_read_files

        self._ws = None  # Websocket connection
        self._session_id = None  # CDP session ID from Target.attachToTarget
        self._target_id = None  # Page the session is attached to
        # Private context of the page, see `_open_private_page()`.
        self._browser_context_id = None
        self.proc = None  # Headless browser Popen object
        self._user_data_dir = None
        self._current_port = None
        self._browser_pid = None

        self.__id = 0

    @property
    def executable(self):
        return self._executable

    @executable.setter
    def executable(self, value):
        self._executable = find_chrome(value)

    @property
    def disable_logging(self):
        return self._disable_logging

    @disable_logging.setter
    def disable_logging(self, value):
        self._disable_logging = value

    @staticmethod
    def _normalize_input(input_value):
        if os.path.exists(input_value):
            return Path(input_value).resolve().as_uri()

        parsed = urlparse(input_value)
        if parsed.scheme:
            return input_value

        return input_value

    def _start_chrome(self):
        """Launch a headless Chrome instance with CDP enabled.

        If Chrome was already started, this is a no-op.
        """
        # self.proc cannot tell if Chrome is running: the launched process
        # may hand over to another one and exit (Edge does so on Windows).
        if self._user_data_dir is not None:
            return  # Already started

        self._user_data_dir = tempfile.mkdtemp(prefix='html2image_cdp_')
        self._current_port = self.cdp_port

        requested_port = self.cdp_port if self.cdp_port is not None else 0

        if not self.disable_logging:
            logger.info(
                'Starting headless Chrome with --remote-debugging-port=%s.',
                requested_port,
            )

        launch_flags = [
            flag for flag in self.flags
            if not flag.startswith(VIRTUAL_TIME_BUDGET_FLAG)
        ]
        if '--remote-allow-origins=*' not in launch_flags:
            launch_flags.append('--remote-allow-origins=*')
        if os.name == 'nt' and not any(
            flag in launch_flags
            for flag in (DISABLE_GRAPHITE_FLAG, '--enable-skia-graphite')
        ):
            launch_flags.append(DISABLE_GRAPHITE_FLAG)
        if self.allow_scripts_to_read_files:
            launch_flags.append('--allow-file-access-from-files')
        if self.max_concurrency > 1:
            launch_flags += [
                flag for flag in WINDOW_FLAGS if flag not in launch_flags
            ]

        command = [
            f'{self.executable}',
            '--window-size=1920,1080',
            f'--remote-debugging-port={requested_port}',
            f'--user-data-dir={self._user_data_dir}',
            '--headless=new',
            '--no-first-run',
            '--no-default-browser-check',
            *launch_flags,
        ]

        if self.print_command:
            print(' '.join(command))

        popen_kwargs = {}
        if self.disable_logging:
            popen_kwargs['stdout'] = subprocess.DEVNULL
            popen_kwargs['stderr'] = subprocess.DEVNULL

        self.proc = subprocess.Popen(command, **popen_kwargs, shell=False)

    def _get_current_port(self):
        if self._current_port is not None:
            return self._current_port

        active_port_file = Path(self._user_data_dir, 'DevToolsActivePort')
        port_line = active_port_file.read_text(encoding='utf-8').splitlines()[0]
        self._current_port = int(port_line)
        return self._current_port

    def _connect_ws(self, new_window=False):
        """Connect to Chrome's browser-level CDP WebSocket and attach to a page target.

        If Chrome has not been started yet, it will be started automatically.
        With `new_window`, the page target will be a new window.
        """
        # Auto-start Chrome if not running
        self._start_chrome()

        max_retries = 30
        retry_delay = 0.5

        for attempt in range(max_retries):
            try:
                current_port = self._get_current_port()
                # Get the browser-level WebSocket URL from /json/version
                response = requests.get(
                    f'http://127.0.0.1:{current_port}/json/version',
                    timeout=2,
                )
                version_info = response.json()
                ws_url = version_info['webSocketDebuggerUrl']

                # Chrome often returns ws://localhost:...; normalize to IPv4 loopback
                # to avoid intermittent IPv6 localhost resolution failures on Windows.
                if ws_url.startswith('ws://localhost:'):
                    ws_url = f"ws://127.0.0.1:{ws_url[len('ws://localhost:'):]}"

                logger.debug('Connecting to browser WebSocket: %s', ws_url)
                self._ws = create_connection(ws_url, timeout=10)
                logger.debug('Connected to browser WebSocket.')
                self._browser_pid = self._find_browser_pid()
                self._deny_downloads()

                # Discover page targets and attach to the first one
                self._attach_to_page_target(new_window)
                return
            except Exception as error:
                if self._ws:
                    try:
                        self._ws.close()
                    except Exception:
                        pass
                    finally:
                        self._ws = None
                        self._session_id = None

                if attempt < max_retries - 1:
                    logger.debug(
                        'CDP connection attempt %d/%d failed: %s. Retrying in %.1fs...',
                        attempt + 1, max_retries, error, retry_delay,
                    )
                    time.sleep(retry_delay)
                else:
                    port_description = (
                        self._current_port
                        if self._current_port is not None
                        else 'an automatically assigned port'
                    )
                    raise BrowserError(
                        f'Could not connect to Chrome CDP on port {port_description} '
                        f'after {max_retries} attempts. Is Chrome running?'
                    ) from error

    def _find_browser_pid(self):
        """Return the process ID of the browser, or None if Chrome does not
        tell it.

        It is not always the ID of the launched process, which may hand
        over to the browser process and exit, as Edge does on Windows.
        """
        try:
            info_id = self.cdp_send('SystemInfo.getProcessInfo')
            processes = self._wait_for_result(info_id)['result']['processInfo']
        except BrowserError:
            return None
        return next(
            (
                process['id'] for process in processes
                if process['type'] == 'browser'
            ),
            None,
        )

    def _deny_downloads(self, **context):
        """Keep Chrome from saving the files that a URL downloads.

        By default, Chrome would save them in the user's Downloads folder.
        Without `browserContextId`, this applies to the pages that are not
        in a private context.
        """
        try:
            self._send_to_browser(
                'Browser.setDownloadBehavior', behavior='deny', **context
            )
        except BrowserError:
            logger.debug('Could not keep Chrome from saving downloads.')

    def _attach_to_page_target(self, new_window=False):
        """Discover page targets and attach to the first one with a
        flattened session.

        With `new_window`, a new window is opened and attached to instead.
        """
        targets_id = self.cdp_send('Target.getTargets')
        targets_result = self._wait_for_result(targets_id)

        targets = targets_result.get('result', {}).get('targetInfos', [])
        page_targets = [t for t in targets if t.get('type') == 'page']

        if new_window or not page_targets:
            # Without `new_window`, Chrome started but has not created a
            # page target yet.
            logger.debug('Creating an about:blank target.')
            create_id = self.cdp_send(
                'Target.createTarget', url='about:blank', newWindow=new_window
            )
            create_result = self._wait_for_result(create_id)
            target_id = create_result.get('result', {}).get('targetId')
            if not target_id:
                raise BrowserError('Failed to create a page target in Chrome.')
        else:
            target_id = page_targets[0]['targetId']

        logger.debug('Attaching to page target: %s', target_id)

        # Attach with flatten=True for session-scoped command routing
        attach_id = self.cdp_send(
            'Target.attachToTarget',
            targetId=target_id,
            flatten=True,
        )
        attach_result = self._wait_for_result(attach_id)

        self._session_id = attach_result.get('result', {}).get('sessionId')
        if not self._session_id:
            raise BrowserError(
                'Failed to get sessionId from Target.attachToTarget.'
            )
        self._target_id = target_id

        logger.debug('Attached with sessionId: %s', self._session_id)

    def _open_window(self, new_window=True):
        """Return a copy of this object, with its own WebSocket connection
        to Chrome, attached to a window of its own.

        Without `new_window`, the window is the page that Chrome opened.
        A copy only captures pages, it never starts or stops Chrome, and
        never uses its locks. Its connection is never set back to None, so
        that it never connects again by itself, see `ws`.
        """
        window = copy.copy(self)
        window._ws = window._session_id = window._windows = None
        window._connect_ws(new_window)
        # The page of the window, whichever page it takes a screenshot in.
        window._window_target_id = window._target_id
        return window

    def _close_window(self, window):
        """Close the page target of `window`, and the private context of
        its screenshot, see `_replace_window()`.

        Return False if Chrome did not answer.
        """
        try:
            requests.put(
                f'http://127.0.0.1:{self._current_port}/json/close/'
                f'{window._window_target_id}',
                timeout=2,
            )
            if window._browser_context_id:
                self._send_to_browser(
                    'Target.disposeBrowserContext',
                    browserContextId=window._browser_context_id,
                )
        except (requests.RequestException, BrowserError):
            return False
        return True

    def _open_private_page(self, new_window=False, blank_start_page=False):
        """Open a page in a new private context, which has its own
        cookies, storage and cache, and attach to it, see
        `ConcurrentBrowser._page()`.

        The page will always be in a new window, whatever `new_window`:
        Chrome cannot open a tab in a context that has no window yet. With
        `blank_start_page`, the page attached to before, which Chrome opened
        when it started, will first be left blank: its page will stop
        running, and Chrome will always keep a page.
        """
        if blank_start_page:
            self._leave_page()
        context = self._send_to_browser('Target.createBrowserContext')
        self._browser_context_id = context['browserContextId']
        self._deny_downloads(browserContextId=self._browser_context_id)
        self._target_id = self._send_to_browser(
            'Target.createTarget',
            url='about:blank',
            browserContextId=self._browser_context_id,
            newWindow=True,
        )['targetId']
        self._session_id = self._send_to_browser(
            'Target.attachToTarget', targetId=self._target_id, flatten=True
        )['sessionId']
        return True

    def _close_page(self):
        """Close the page, with its private context, see
        `ConcurrentBrowser._page()`."""
        context, self._browser_context_id = self._browser_context_id, None
        self._target_id = self._session_id = None
        self._send_to_browser(
            'Target.disposeBrowserContext', browserContextId=context
        )

    def _leave_page(self):
        """Leave the page blank, so that it stops running, see
        `ConcurrentBrowser._page()`.

        With `isolate_pages=False`, an alert that it showed after its
        screenshot would otherwise block the next one for 30 seconds. The
        tab will keep the cookies, the storage and the name of its window.
        """
        self._wait_for_result(
            self.cdp_send('Page.navigate', url='about:blank')
        )

    def _send_to_browser(self, method, **params):
        """Send a command to Chrome itself, not to the page, and return
        its result.

        The messages of the pages are ignored until the answer comes, among
        which those of a page that is being closed.
        """
        session_id, self._session_id = self._session_id, None
        try:
            return self._wait_for_result(
                self.cdp_send(method, **params)
            )['result']
        finally:
            self._session_id = session_id

    @property
    def ws(self):
        if not self._ws:
            self._connect_ws()
        return self._ws

    @property
    def _id(self):
        self.__id += 1
        return self.__id

    def cdp_send(self, method, **params):
        """Send a CDP command via WebSocket. Returns the message ID."""
        # Access self.ws first - it may trigger _connect_ws() which
        # establishes the session and sets self._session_id.
        ws = self.ws
        msg_id = self._id
        payload = {
            'id': msg_id,
            'method': method,
            'params': params,
        }
        if self._session_id:
            payload['sessionId'] = self._session_id

        logger.debug('cdp_send: %s %s', method, params)
        try:
            ws.send(json.dumps(payload))
        except CONNECTION_ERRORS as error:
            raise BrowserError(CONNECTION_LOST) from error
        return msg_id

    def _receive(self):
        """Return the next message from Chrome.

        Timeouts are raised as they are, for the caller to describe.
        """
        try:
            raw = self.ws.recv()
        except TIMEOUT_ERRORS:
            raise
        except CONNECTION_ERRORS as error:
            raise BrowserError(CONNECTION_LOST) from error
        return read_message(raw)

    def _wait_for_result(self, msg_id, timeout=CDP_TIMEOUT):
        """Wait for a CDP response matching the given message ID.

        Returns the full response message.
        """
        return self._recv_until(
            lambda msg: msg if msg.get('id') == msg_id else None,
            timeout=timeout,
        )

    def _recv_until(self, predicate, timeout=CDP_TIMEOUT):
        """Receive WebSocket messages until predicate(message) returns a truthy value.

        Returns the value returned by the predicate on match.
        Raises TimeoutError if no matching message is received within timeout.
        """
        self.ws.settimeout(timeout)
        try:
            while True:
                message = self._receive()

                # Ignore events/responses from other sessions when attached.
                if not self._message_matches_current_session(message):
                    continue

                # Check for CDP errors
                if 'error' in message:
                    error = message['error']
                    raise BrowserError(
                        f'CDP error {error.get("code")}: {error.get("message")}'
                    )

                if message.get('method') == 'Inspector.detached':
                    reason = message.get('params', {}).get('reason')
                    raise BrowserError(f'Chrome page was lost: {reason}')

                logger.debug('CDP recv: %s', message)
                result = predicate(message)
                if result:
                    return result
        except TIMEOUT_ERRORS:
            raise BrowserTimeoutError(
                f'Timed out after {timeout}s waiting for CDP response.'
            )
        finally:
            self.ws.settimeout(None)

    def _message_matches_current_session(self, message):
        """Return True if the message belongs to the active CDP session,
        or, without one, to Chrome itself."""
        return message.get('sessionId') == self._session_id

    def _wait_for_navigation_complete(self, nav_id, timeout=CDP_TIMEOUT):
        """Wait for Page.navigate response and page-load completion together.

        This avoids missing a fast load event between two separate waits.
        Only the load event of the document created by this navigation is
        taken into account, events of a previous page are ignored.

        An error answer to Page.navigate is returned, see `_navigate()`.
        """
        deadline = time.time() + timeout
        nav_result = None
        loaded_documents = set()

        try:
            while time.time() < deadline:
                self.ws.settimeout(max(0.1, deadline - time.time()))
                message = self._receive()

                # Ignore events/responses from other sessions when attached.
                if not self._message_matches_current_session(message):
                    continue

                if 'error' in message and message.get('id') != nav_id:
                    error = message['error']
                    raise BrowserError(
                        f'CDP error {error.get("code")}: {error.get("message")}'
                    )

                if message.get('method') == 'Inspector.detached':
                    reason = message.get('params', {}).get('reason')
                    raise BrowserError(f'Chrome page was lost: {reason}')

                logger.debug('CDP recv: %s', message)

                if message.get('id') == nav_id:
                    nav_result = message
                    error_text = nav_result.get('result', {}).get('errorText')
                    if error_text or 'error' in nav_result:
                        return nav_result

                    # No document is loaded when navigating within the
                    # current one (e.g. to another anchor of the same page).
                    if 'loaderId' not in nav_result.get('result', {}):
                        return nav_result

                if message.get('method') == 'Page.lifecycleEvent':
                    params = message['params']
                    if params['name'] == 'load':
                        loaded_documents.add(params['loaderId'])

                if nav_result and (
                    nav_result['result'].get('loaderId') in loaded_documents
                ):
                    return nav_result
        except TIMEOUT_ERRORS:
            pass
        finally:
            self.ws.settimeout(None)

        raise PageLoadTimeoutError(
            f'Timed out after {timeout}s waiting for page navigation.'
        )

    def _navigate(self, url):
        """Load `url` in the page.

        Return the error text if the page could not be loaded. Chrome gives
        it in its answer to Page.navigate, either as an error text or as an
        error answer, for example for an invalid URL.
        """
        nav_id = self.cdp_send('Page.navigate', url=url)
        logger.debug('Waiting for navigation and load events...')
        nav_result = self._wait_for_navigation_complete(nav_id)
        return (
            nav_result.get('result', {}).get('errorText')
            or nav_result.get('error', {}).get('message')
        )

    def _virtual_time_budget(self):
        """Return the value of the `--virtual-time-budget` flag, if set."""
        for flag in self.flags:
            if flag.startswith(VIRTUAL_TIME_BUDGET_FLAG):
                return int(flag[len(VIRTUAL_TIME_BUDGET_FLAG):])
        return None

    def _spend_virtual_time(self, budget):
        """Let the page run for `budget` milliseconds of virtual time."""
        self.cdp_send(
            'Emulation.setVirtualTimePolicy',
            policy='pauseIfNetworkFetchesPending',
            budget=budget,
        )
        self._recv_until(
            lambda msg: msg.get('method') == 'Emulation.virtualTimeBudgetExpired'
        )

        # Virtual time is paused once the budget is spent.
        resume_id = self.cdp_send(
            'Emulation.setVirtualTimePolicy',
            policy='advance',
        )
        self._wait_for_result(resume_id)

    def _print_to_pdf(self, output_file_path, options):
        """Print the current page to a PDF file."""
        logger.debug('Printing to PDF...')
        top, right, bottom, left = options['margin']
        pdf_id = self.cdp_send(
            'Page.printToPDF',
            paperWidth=options['width'],
            paperHeight=options['height'],
            marginTop=top,
            marginRight=right,
            marginBottom=bottom,
            marginLeft=left,
            printBackground=options['background'],
            scale=options['scale'],
            # Let a CSS `@page` size win, as Firefox always does.
            preferCSSPageSize=True,
        )
        pdf_data = self._wait_for_result(pdf_id).get('result', {}).get('data')
        if not pdf_data:
            raise BrowserError('No PDF data received from Chrome.')

        with open(output_file_path, 'wb') as file_obj:
            file_obj.write(base64.b64decode(pdf_data))

    def _evaluate(self, expression):
        """Return the value of a JavaScript expression that returns JSON."""
        evaluate_id = self.cdp_send(
            'Runtime.evaluate', expression=expression, awaitPromise=True,
        )
        result = self._wait_for_result(evaluate_id)['result']
        if 'exceptionDetails' in result:
            # The text is only "Uncaught": the error itself is described in
            # the exception.
            details = result['exceptionDetails']
            description = details.get('exception', {}).get('description')
            raise BrowserError(
                f'JavaScript error: {description or details["text"]}'
            )
        return json.loads(result['result']['value'])

    def _capture(self, output_file_path, clip, beyond_viewport=False):
        """Save an image of the `clip` area of the page.

        With `beyond_viewport`, the area can be outside of the viewport.
        """
        logger.debug('Capturing screenshot...')

        ext = os.path.splitext(output_file_path)[1].lower()
        capture_format = 'jpeg' if ext in ('.jpg', '.jpeg') else 'png'
        transparent_bg_set = False
        if capture_format == 'png':
            bg_id = self.cdp_send(
                'Emulation.setDefaultBackgroundColorOverride',
                color={'r': 0, 'g': 0, 'b': 0, 'a': 0},
            )
            self._wait_for_result(bg_id)
            transparent_bg_set = True
        else:
            # Ensure no transparent override is active for JPEG captures.
            bg_id = self.cdp_send(
                'Emulation.setDefaultBackgroundColorOverride'
            )
            self._wait_for_result(bg_id)

        try:
            screenshot_id = self.cdp_send(
                'Page.captureScreenshot',
                format=capture_format,
                omitBackground=(capture_format == 'png'),
                clip={**clip, 'scale': 1},
                fromSurface=True,
                captureBeyondViewport=beyond_viewport,
            )
            screenshot_result = self._wait_for_result(screenshot_id)
        finally:
            if transparent_bg_set:
                try:
                    clear_id = self.cdp_send(
                        'Emulation.setDefaultBackgroundColorOverride'
                    )
                    self._wait_for_result(clear_id)
                except Exception:
                    logger.debug(
                        'Could not clear CDP background override.',
                        exc_info=True,
                    )

        img_data = screenshot_result.get('result', {}).get('data')
        if not img_data:
            raise BrowserError('No screenshot data received from Chrome.')

        with open(output_file_path, 'wb') as file_obj:
            file_obj.write(base64.b64decode(img_data))

    def _capture_elements(self, output_path, elements, padding):
        """Save an image of each element, see `screenshot()`."""
        _selector.check_selectors(
            self._evaluate, [selector for selector, _ in elements]
        )

        missing, too_large = [], []
        for element in elements:
            selector, output_file = element
            # The page is scrolled back as loaded after each element, so
            # that each image is the same as with one call per selector.
            box = self._evaluate(_selector.element_box_js(selector))
            clip = _selector.element_clip(box, padding)
            if clip is None:
                missing.append(element)
            elif max(clip['width'], clip['height']) > MAX_CAPTURE_SIZE:
                too_large.append(element)
            else:
                # Capturing beyond the viewport sends the page a resize
                # event, see `_chromium_page_fit._Tiles`. An element that
                # the viewport already shows will be captured from it.
                shown = _selector.viewport_scroll(box, clip) == (
                    box['scrollX'], box['scrollY']
                )
                self._capture(
                    os.path.join(output_path, output_file), clip,
                    beyond_viewport=not shown,
                )
            if box is not None:
                self._evaluate(_selector.restore_js(selector, box))
        return missing, too_large

    def screenshot(
        self,
        input,
        output_path,
        output_file='screenshot.png',
        size=(1920, 1080),
        pdf_options=None,
        elements=None,
        selector_padding=0,
        full_page=False,
        full_page_stability_timeout=None,
        full_page_profile='balanced',
        full_page_fixed_elements='auto',
        full_page_max_pixels=DEFAULT_MAX_PIXELS,
    ):
        """Take a screenshot using Chrome DevTools Protocol.

        If `pdf_options` is given, the page is printed to a PDF instead.

        If `elements` is given, as a list of (selector, output_file) pairs,
        an image of each element is saved instead, with `selector_padding`
        pixels around it, and `output_file` is not used. The elements that
        could not be captured are returned, as two lists of these pairs:
        the missing elements, and the elements too large to be captured.

        If `full_page` is True, an image of the whole page will be saved
        instead, see `_chromium_page_fit.capture_full_page()`.

        See: https://chromedevtools.github.io/devtools-protocol/
        """
        target_url = self._normalize_input(input)
        with self._window() as window:
            enable_id = window.cdp_send('Page.enable')
            window._wait_for_result(enable_id)

            lifecycle_id = window.cdp_send(
                'Page.setLifecycleEventsEnabled',
                enabled=True,
            )
            window._wait_for_result(lifecycle_id)

            # Set viewport metrics before navigation so layout-sensitive pages
            # compute against the final viewport dimensions.
            metrics_id = window.cdp_send(
                'Emulation.setDeviceMetricsOverride',
                width=size[0],
                height=size[1],
                deviceScaleFactor=1,
                mobile=False,
            )
            window._wait_for_result(metrics_id)

            error_text = window._navigate(target_url)
            if error_text == CERT_VERIFIER_CHANGED:
                error_text = window._navigate(target_url)
            if error_text:
                disable_id = window.cdp_send('Page.disable')
                window._wait_for_result(disable_id)
                raise PageLoadError(f'Navigation failed: {error_text}')

            logger.debug('Page loaded.')
            disable_id = window.cdp_send('Page.disable')
            window._wait_for_result(disable_id)

            virtual_time_budget = window._virtual_time_budget()
            if virtual_time_budget:
                window._spend_virtual_time(virtual_time_budget)

            if pdf_options is not None:
                window._print_to_pdf(
                    os.path.join(output_path, output_file), pdf_options
                )
                return

            if elements is not None:
                return window._capture_elements(
                    output_path, elements, selector_padding
                )

            if full_page:
                _chromium_page_fit.capture_full_page(
                    window,
                    output_path,
                    output_file,
                    size[0],
                    size[1],
                    stability_timeout=full_page_stability_timeout,
                    profile=full_page_profile,
                    fixed_elements=full_page_fixed_elements,
                    max_pixels=full_page_max_pixels,
                )
                return

            window._capture(
                os.path.join(output_path, output_file),
                {'x': 0, 'y': 0, 'width': size[0], 'height': size[1]},
            )

    def _kill_browser(self):
        """Kill the browser process and the processes it started.

        Only used on Windows. Elsewhere, the launched process is the
        browser, and it is stopped in `__exit__()`.
        """
        if self._browser_pid is None:
            return
        logger.debug('Killing Chrome.')
        subprocess.run(
            ['taskkill', '/PID', str(self._browser_pid), '/T', '/F'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    def _wait_for_close(self, timeout=5):
        """Wait for Chrome to close the WebSocket, which it does on exit."""
        self._ws.settimeout(timeout)
        try:
            while True:
                self._ws.recv()
        except WebSocketConnectionClosedException:
            pass

    def __enter__(self):
        """Start a headless Chrome instance with CDP enabled."""
        with self._lock:
            try:
                self._connect_ws()
                if self.max_concurrency > 1:
                    # The first window is the page that Chrome opened.
                    self._windows = [
                        self._open_window(new_window=index > 0)
                        for index in range(self.max_concurrency)
                    ]
                return self
            except Exception:
                self.__exit__()
                raise

    def __exit__(self, *exc):
        """Shut down the headless Chrome instance and clean up resources."""
        with self._lock:
            # The windows in use will be closed with Chrome, and their
            # captures will fail.
            for window in self._windows or []:
                window._ws.close()
            self._windows = None
            self._stop_chrome()

    def _stop_chrome(self):
        """Close Chrome and delete its profile, see `__exit__()`."""
        if not self.disable_logging:
            logger.info(
                'Closing headless Chrome instance on port %s.',
                self._current_port,
            )

        # Close WebSocket and CDP connection
        if self._ws:
            try:
                # Browser.close is a browser-level command, send without sessionId
                self._session_id = None
                self.cdp_send('Browser.close')
                self._wait_for_close()
                self._ws.close()
                logger.debug('Closed CDP and WebSocket connections.')
            except WebSocketTimeoutException:
                # Chrome did not close in time. On Windows, the launched
                # process may have already exited, as with Edge, so
                # stopping it below would not stop the browser.
                if os.name == 'nt':
                    self._kill_browser()
            except Exception:
                logger.debug(
                    'Could not properly close CDP/WebSocket connections.',
                    exc_info=True,
                )
            finally:
                self._ws = None
                self._session_id = None

        # Terminate the Chrome process
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
                logger.debug('Chrome process terminated.')
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
                logger.debug('Chrome process killed after timeout.')
            except Exception:
                logger.debug(
                    'Could not properly stop Chrome.',
                    exc_info=True,
                )
            finally:
                if os.name == 'nt':
                    subprocess.run(
                        ['taskkill', '/PID', str(self.proc.pid), '/T', '/F'],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )

        # Clean up temporary user data directory
        if self._user_data_dir:
            remove_profile(self._user_data_dir)
            self._user_data_dir = None

        self.proc = None
        self._current_port = None
        self._browser_pid = None
        self._browser_context_id = None
        self._start_page_used = False
