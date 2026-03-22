from .browser import Browser
from .search_utils import find_firefox

import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

logger = logging.getLogger(__name__)


class FirefoxHeadlessScreenshot(Browser):
    """Firefox CLI screenshot backend using the --screenshot flag.

    Known limitations:
    - JPEG output is not natively supported; .jpg/.jpeg extensions still
      produce PNG-encoded files on most Firefox versions.
    - Transparent PNG backgrounds for standalone SVG files may not render
      correctly.
    """

    def __init__(
        self,
        executable=None,
        flags=None,
        print_command=False,
        disable_logging=False,
    ):
        self.executable = executable
        if not flags:
            self.flags = []
        else:
            self.flags = [flags] if isinstance(flags, str) else list(flags)

        self.print_command = print_command
        self._disable_logging = disable_logging

    @property
    def executable(self):
        return self._executable

    @executable.setter
    def executable(self, value):
        self._executable = find_firefox(value)

    @property
    def disable_logging(self):
        return self._disable_logging

    @disable_logging.setter
    def disable_logging(self, value):
        self._disable_logging = value

    def screenshot(
        self,
        input,
        output_path,
        output_file='screenshot.png',
        size=(1920, 1080),
    ):
        """Take a screenshot using Firefox's --screenshot CLI flag."""
        width, height = size if size else (1920, 1080)

        ext = os.path.splitext(output_file)[1].lower()
        if ext in ('.jpg', '.jpeg'):
            raise ValueError(
                "FirefoxHeadlessScreenshot does not support JPEG output : "
                "Firefox --screenshot always produces PNG. "
                "Use a .png extension, or switch to browser='firefox-bidi' for JPEG support."
            )

        if os.path.exists(input):
            target_url = Path(input).resolve().as_uri()
        else:
            target_url = input

        profile_dir = tempfile.mkdtemp(prefix='html2image_firefox_cli_')
        try:
            output_full_path = os.path.join(output_path, output_file)
            command = [
                str(self.executable),
                '--headless',
                '-no-remote',
                '--new-instance',
                '--profile', profile_dir,
                f'--window-size={width},{height}',
                f'--screenshot={output_full_path}',
                target_url,
                *self.flags,
            ]

            if self.print_command:
                print(' '.join(command))

            if not self.disable_logging:
                logger.info('Running Firefox CLI screenshot.')

            popen_kwargs = {}
            if self.disable_logging:
                popen_kwargs['stdout'] = subprocess.DEVNULL
                popen_kwargs['stderr'] = subprocess.DEVNULL

            subprocess.run(command, check=False, **popen_kwargs)

            if not os.path.isfile(output_full_path):
                raise RuntimeError(
                    f'Firefox --screenshot did not produce {output_full_path!r}. '
                    'Note: JPEG output is not supported; only PNG files are produced.'
                )
        finally:
            shutil.rmtree(profile_dir, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass
