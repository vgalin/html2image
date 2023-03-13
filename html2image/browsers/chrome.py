from .browser import Browser
from .search_utils import get_command_origin, find_first_defined_env_var

import subprocess
import platform
import os
import shutil

ENV_VAR_LOOKUP_TOGGLE = 'HTML2IMAGE_TOGGLE_ENV_VAR_LOOKUP'

CHROME_EXECUTABLE_ENV_VAR_CANDIDATES = [
    'HTML2IMAGE_CHROME_BIN',
    'HTML2IMAGE_CHROME_EXE',
    'CHROME_BIN',
    'CHROME_EXE',
]


def _find_chrome(user_given_executable=None):
    """ Finds a Chrome executable.

    Search Chrome on a given path. If no path given,
    try to find Chrome or Chromium-browser on a Windows or Unix system.

    Parameters
    ----------
    - `user_given_executable`: str (optional)
        + A filepath leading to a Chrome/ Chromium executable
        + Or a filename found in the current working directory
        + Or a keyword that executes Chrome/ Chromium, ex:
            - 'chromium' on linux systems
            - 'chrome' on windows (if typing `start chrome` in a cmd works)

    Raises
    ------
    - `FileNotFoundError`
        + If a suitable chrome executable could not be found.

    Returns
    -------
    - str
        + Path of the chrome executable on the current machine.
    """

    # try to find a chrome bin/exe in ENV
    path_from_env = find_first_defined_env_var(
        env_var_list=CHROME_EXECUTABLE_ENV_VAR_CANDIDATES,
        toggle=ENV_VAR_LOOKUP_TOGGLE
    )

    if path_from_env:
        print(
            f'Found a potential chrome executable in the {path_from_env} '
            f'environment variable:\n{path_from_env}\n'
        )
        return path_from_env

    # if an executable is given, try to use it
    if user_given_executable is not None:

        # On Windows, we cannot "safely" validate that user_given_executable
        # seems to be a chrome executable, as we cannot run it with
        # the --version flag.
        # https://bugs.chromium.org/p/chromium/issues/detail?id=158372
        #
        # We thus do the "bare minimum" and check if user_given_executable
        # is a file, a filepath, or corresponds to a keyword that can be used
        # with the start command, like so: `start user_given_executable`
        if platform.system() == 'Windows':
            command_origin = get_command_origin(user_given_executable)
            if command_origin:
                return command_origin

            # cannot validate user_given_executable
            raise FileNotFoundError()

        # On a non-Windows OS, we can validate in a basic way that
        # user_given_executable leads to a Chrome / Chromium executable,
        # or is a command, using the --version flag
        else:
            try:
                if 'chrom' in subprocess.check_output(
                    [user_given_executable, '--version']
                ).decode('utf-8').lower():
                    return user_given_executable
            except Exception:
                pass

        # We got a user_given_executable but couldn't validate it
        raise FileNotFoundError(
            'Failed to find a seemingly valid chrome executable '
            'in the given path.'
        )

    # Executable not in ENV or given by the user, try to find it
    # Search for executable on a Windows OS
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

    # Search for executable on a Linux OS
    elif platform.system() == "Linux":

        chrome_commands = [
            'chromium',
            'chromium-browser',
            'chrome',
            'google-chrome'
        ]

        for chrome_command in chrome_commands:
            if shutil.which(chrome_command):
                # check the --version for "chrom" ?
                return chrome_command

        # snap seems to be a special case?
        # see https://stackoverflow.com/q/63375327/12182226

        try:
            version_result = subprocess.check_output(
                ["chromium-browser", "--version"]
            )
            if 'snap' in str(version_result):
                chrome_snap = (
                    '/snap/chromium/current/usr/lib/chromium-browser/chrome'
                )
                if os.path.isfile(chrome_snap):
                    return chrome_snap
        except Exception:
            pass

    # Search for executable on MacOS
    elif platform.system() == "Darwin":
        # MacOS system
        chrome_app = (
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        )

        try:
            version_result = subprocess.check_output(
                [chrome_app, "--version"]
            )
            if "Google Chrome" in str(version_result):
                return chrome_app
        except Exception:
            pass

    # Couldn't find an executable (or OS not in Windows, Linux or Mac)
    raise FileNotFoundError(
        'Could not find a Chrome executable on this '
        'machine, please specify it yourself.'
    )


class ChromeHeadless(Browser):
    """
        Chrome/Chromium browser wrapper.

        Parameters
        ----------
        - `executable` : str, optional
            + Path to a chrome executable.

        - `flags` : list of str
            + Flags to be used by the headless browser.
            + Default flags are :
                - '--default-background-color=000000'
                - '--hide-scrollbars'
        - `print_command` : bool
            + Whether or not to print the command used to take a screenshot.
    """

    def __init__(self, executable=None, flags=None, print_command=False):
        self.executable = executable
        if not flags:
            self.flags = [
                '--default-background-color=000000',
                '--hide-scrollbars',
            ]
        else:
            self.flags = [flags] if isinstance(flags, str) else flags

        self.print_command = print_command

    @property
    def executable(self):
        return self._executable

    @executable.setter
    def executable(self, value):
        self._executable = _find_chrome(value)

    def screenshot(
        self,
        input,
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

        if not input:
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
            f'{self.executable}',
            '--headless',
            f'--screenshot={os.path.join(output_path, output_file)}',
            f'--window-size={size[0]},{size[1]}',
            *self.flags,
            f'{input}',
        ]

        if self.print_command:
            print(' '.join(command))

        subprocess.run(command)
