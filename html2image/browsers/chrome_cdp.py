from .browser import CDPBrowser
from .search_utils import find_chrome

import base64
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
from urllib.parse import urlparse

import requests
from websocket import WebSocketTimeoutException, create_connection

logger = logging.getLogger(__name__)

# Default timeout (in seconds) for waiting on CDP responses
CDP_TIMEOUT = 30


class ChromeCDP(CDPBrowser):

    def __init__(
        self, executable=None, flags=None,
        print_command=False, cdp_port=9222,
        disable_logging=False,
    ):
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

        self._ws = None  # Websocket connection
        self._session_id = None  # CDP session ID from Target.attachToTarget
        self.proc = None  # Headless browser Popen object
        self._user_data_dir = None

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

        If Chrome is already running (self.proc is not None and alive),
        this is a no-op.
        """
        if self.proc is not None and self.proc.poll() is None:
            return  # Already running

        self._user_data_dir = tempfile.mkdtemp(prefix='html2image_cdp_')

        if not self.disable_logging:
            logger.info(
                'Starting headless Chrome with --remote-debugging-port=%s.',
                self.cdp_port,
            )

        launch_flags = list(self.flags)
        if '--remote-allow-origins=*' not in launch_flags:
            launch_flags.append('--remote-allow-origins=*')

        command = [
            f'{self.executable}',
            '--window-size=1920,1080',
            f'--remote-debugging-port={self.cdp_port}',
            f'--user-data-dir={self._user_data_dir}',
            '--headless=new',
            '--no-first-run',
            '--no-default-browser-check',
            '--allow-file-access-from-files',
            *launch_flags,
        ]

        if self.print_command:
            print(' '.join(command))

        popen_kwargs = {}
        if self.disable_logging:
            popen_kwargs['stdout'] = subprocess.DEVNULL
            popen_kwargs['stderr'] = subprocess.DEVNULL

        self.proc = subprocess.Popen(command, **popen_kwargs, shell=False)

    def _connect_ws(self):
        """Connect to Chrome's browser-level CDP WebSocket and attach to a page target.

        If Chrome has not been started yet, it will be started automatically.
        """
        # Auto-start Chrome if not running
        self._start_chrome()

        max_retries = 10
        retry_delay = 0.5

        for attempt in range(max_retries):
            try:
                # Get the browser-level WebSocket URL from /json/version
                response = requests.get(
                    f'http://127.0.0.1:{self.cdp_port}/json/version',
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

                # Discover page targets and attach to the first one
                self._attach_to_page_target()
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
                    raise RuntimeError(
                        f'Could not connect to Chrome CDP on port {self.cdp_port} '
                        f'after {max_retries} attempts. Is Chrome running?'
                    ) from error

    def _attach_to_page_target(self):
        """Discover page targets and attach to the first one with a flattened session."""
        targets_id = self.cdp_send('Target.getTargets')
        targets_result = self._wait_for_result(targets_id)

        targets = targets_result.get('result', {}).get('targetInfos', [])
        page_targets = [t for t in targets if t.get('type') == 'page']

        if not page_targets:
            # Chrome started but has not created a page target yet.
            logger.debug('No page targets found - creating about:blank target.')
            create_id = self.cdp_send('Target.createTarget', url='about:blank')
            create_result = self._wait_for_result(create_id)
            target_id = create_result.get('result', {}).get('targetId')
            if not target_id:
                raise RuntimeError('Failed to create a page target in Chrome.')
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
            raise RuntimeError(
                'Failed to get sessionId from Target.attachToTarget.'
            )

        logger.debug('Attached with sessionId: %s', self._session_id)

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
        ws.send(json.dumps(payload))
        return msg_id

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
                raw = self.ws.recv()
                message = json.loads(raw)

                # Ignore events/responses from other sessions when attached.
                if not self._message_matches_current_session(message):
                    continue

                # Check for CDP errors
                if 'error' in message:
                    error = message['error']
                    raise RuntimeError(
                        f'CDP error {error.get("code")}: {error.get("message")}'
                    )

                logger.debug('CDP recv: %s', message)
                result = predicate(message)
                if result:
                    return result
        except (TimeoutError, socket.timeout, WebSocketTimeoutException):
            raise TimeoutError(
                f'Timed out after {timeout}s waiting for CDP response.'
            )
        finally:
            self.ws.settimeout(None)

    def _message_matches_current_session(self, message):
        """Return True if the message belongs to the active CDP session."""
        if not self._session_id:
            return True

        return message.get('sessionId') == self._session_id

    def _wait_for_navigation_complete(self, nav_id, timeout=CDP_TIMEOUT):
        """Wait for Page.navigate response and page-load completion together.

        This avoids missing a fast load event between two separate waits.
        """
        deadline = time.time() + timeout
        nav_result = None
        page_loaded = False

        self.ws.settimeout(timeout)
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TimeoutError(
                        f'Timed out after {timeout}s waiting for page load.'
                    )

                self.ws.settimeout(max(0.1, remaining))
                message = json.loads(self.ws.recv())

                # Ignore events/responses from other sessions when attached.
                if not self._message_matches_current_session(message):
                    continue

                if 'error' in message:
                    error = message['error']
                    raise RuntimeError(
                        f'CDP error {error.get("code")}: {error.get("message")}'
                    )

                logger.debug('CDP recv: %s', message)

                if message.get('id') == nav_id:
                    nav_result = message
                    error_text = nav_result.get('result', {}).get('errorText')
                    if error_text:
                        return nav_result

                if message.get('method') in (
                    'Page.loadEventFired',
                    'Page.frameStoppedLoading',
                ):
                    page_loaded = True

                if nav_result and page_loaded:
                    return nav_result
        except (TimeoutError, socket.timeout, WebSocketTimeoutException):
            raise TimeoutError(
                f'Timed out after {timeout}s waiting for page navigation.'
            )
        finally:
            self.ws.settimeout(None)

    def screenshot(
        self,
        input,
        output_path,
        output_file='screenshot.png',
        size=(1920, 1080),
    ):
        """Take a screenshot using Chrome DevTools Protocol.

        See: https://chromedevtools.github.io/devtools-protocol/
        """
        auto_started = self.proc is None or self.proc.poll() is not None
        if auto_started:
            self.__enter__()

        try:
            enable_id = self.cdp_send('Page.enable')
            self._wait_for_result(enable_id)

            # Set viewport metrics before navigation so layout-sensitive pages
            # compute against the final viewport dimensions.
            metrics_id = self.cdp_send(
                'Emulation.setDeviceMetricsOverride',
                width=size[0],
                height=size[1],
                deviceScaleFactor=1,
                mobile=False,
            )
            self._wait_for_result(metrics_id)

            target_url = self._normalize_input(input)
            nav_id = self.cdp_send('Page.navigate', url=target_url)

            logger.debug('Waiting for navigation and load events...')
            nav_result = self._wait_for_navigation_complete(nav_id)

            error_text = nav_result.get('result', {}).get('errorText')
            if error_text:
                disable_id = self.cdp_send('Page.disable')
                self._wait_for_result(disable_id)
                raise RuntimeError(f'Navigation failed: {error_text}')

            logger.debug('Page loaded.')
            disable_id = self.cdp_send('Page.disable')
            self._wait_for_result(disable_id)

            logger.debug('Capturing screenshot...')

            ext = os.path.splitext(output_file)[1].lower()
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
                    clip={
                        'x': 0,
                        'y': 0,
                        'width': size[0],
                        'height': size[1],
                        'scale': 1,
                    },
                    fromSurface=True,
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
                raise RuntimeError('No screenshot data received from Chrome.')

            with open(os.path.join(output_path, output_file), 'wb') as file_obj:
                file_obj.write(base64.b64decode(img_data))
        finally:
            if auto_started:
                self.__exit__()

    def __enter__(self):
        """Start a headless Chrome instance with CDP enabled."""
        self._start_chrome()
        try:
            self._connect_ws()
            return self
        except Exception:
            self.__exit__()
            raise

    def __exit__(self, *exc):
        """Shut down the headless Chrome instance and clean up resources."""
        if not self.disable_logging:
            logger.info(
                'Closing headless Chrome instance on port %s.',
                self.cdp_port,
            )

        # Close WebSocket and CDP connection
        if self._ws:
            try:
                # Browser.close is a browser-level command, send without sessionId
                self._session_id = None
                self.cdp_send('Browser.close')
                self._ws.close()
                logger.debug('Closed CDP and WebSocket connections.')
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
            try:
                shutil.rmtree(self._user_data_dir, ignore_errors=True)
            except Exception:
                pass
            finally:
                self._user_data_dir = None

        self.proc = None
