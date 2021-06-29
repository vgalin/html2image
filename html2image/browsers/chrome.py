from .browser import Browser

import subprocess
import platform
import os
import shutil


def _find_chrome(user_given_path=None):
    """ Finds a Chrome executable.

    Search Chrome on a given path. If no path given,
    try to find Chrome or Chromium-browser on a Windows or Unix system.

    Raises
    ------
    - `FileNotFoundError`
        + If a suitable chrome executable could not be found.

    Returns
    -------
    - str
        + Path of the chrome executable on the current machine.
    """

    # TODO when other browsers will be available:
    # Ensure that the given executable is a chrome one.

    if user_given_path is not None:
        if os.path.isfile(user_given_path):
            return user_given_path
        else:
            raise FileNotFoundError('Could not find chrome in the given path.')

    if platform.system() == 'Windows':
        prefixes = [
            os.getenv('PROGRAMFILES(X86)'),
            os.getenv('PROGRAMFILES'),
            os.getenv('LOCALAPPDATA'),
        ]

        suffix = "Google\\Chrome\\Application\\chrome.exe"

        for prefix in prefixes:
            path_candidate = os.path.join(prefix, suffix)
            if os.path.isfile(path_candidate):
                return path_candidate

    elif platform.system() == "Linux":

        # search google-chrome
        version_result = subprocess.check_output(
            ["google-chrome", "--version"]
        )

        if 'Google Chrome' in str(version_result):
            return "google-chrome"

        # else search chromium-browser

        # snap seems to be a special case?
        # see https://stackoverflow.com/q/63375327/12182226
        version_result = subprocess.check_output(
            ["chromium-browser", "--version"]
        )
        if 'snap' in str(version_result):
            chrome_snap = (
                '/snap/chromium/current/usr/lib/chromium-browser/chrome'
            )
            if os.path.isfile(chrome_snap):
                return chrome_snap
        else:
            which_result = shutil.which('chromium-browser')
            if which_result is not None and os.path.isfile(which_result):
                return which_result

    elif platform.system() == "Darwin":
        # MacOS system
        chrome_app = (
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        )
        version_result = subprocess.check_output(
            [chrome_app, "--version"]
        )
        if "Google Chrome" in str(version_result):
            return chrome_app

    raise FileNotFoundError(
        'Could not find a Chrome executable on this '
        'machine, please specify it yourself.'
    )


class ChromeHeadless(Browser):
    """
        Chrome/Chromium browser wrapper.

        Parameters
        ----------
        - `executable_path` : str, optional
            + Path to a chrome executable.

        - `flags` : list of str
            + Flags to be used by the headless browser.
            + Default flags are :
                - '--default-background-color=0'
                - '--hide-scrollbars'
        - `print_command` : bool
            + Whether or not to print the command used to take a screenshot.
    """

    def __init__(self, executable_path=None, flags=None, print_command=False):
        self.executable_path = executable_path
        if not flags:
            flags = [
                '--default-background-color=0',
                '--hide-scrollbars',
            ]
        self.flags = [flags] if isinstance(flags, str) else flags
        self.print_command = print_command

    @property
    def executable_path(self):
        return self._executable_path

    @executable_path.setter
    def executable_path(self, value):
        self._executable_path = _find_chrome(value)

    def screenshot(
        self,
        input_file,
        output_path,
        output_file='screenshot.png',
        size=(1920, 1080),
    ):
        """ Calls Chrome or Chromium headless to take a screenshot.

            Parameters
            ----------
            - `output_file`: str
                + Name as which the screenshot will be saved.
                + File extension (e.g. .png) has to be included.
                + Default is screenshot.png
            - `input`: str
                + File or url that will be screenshotted.
                + Cannot be None
            - `size`: (int, int), optional
                + Two values representing the window size of the headless
                + browser and by extention, the screenshot size.
                + These two values must be greater than 0.
            Raises
            ------
            - `ValueError`
                + If the value of `size` is incorrect.
                + If `input` is empty.
        """

        if not input_file:
            raise ValueError('The `input` parameter is empty.')

        if size[0] < 1 or size[1] < 1:
            raise ValueError(
                f'Could not screenshot "{output_file}" '
                f'with a size of {size}:\n'
                'A valid size consists of two integers greater than 0.'
            )

        # command used to launch chrome in
        # headless mode and take a screenshot
        command = [
            f'{self.executable_path}',
            '--headless',
            f'--screenshot={os.path.join(output_path, output_file)}',
            f'--window-size={size[0]},{size[1]}',
            *self.flags,
            f'{input_file}',
        ]

        if self.print_command:
            print(f'{command}\n')

        subprocess.run(command)
