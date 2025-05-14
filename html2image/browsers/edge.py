from .chromium import ChromiumHeadless
from .search_utils import get_command_origin, find_first_defined_env_var

import subprocess
import platform
import os
import shutil

ENV_VAR_LOOKUP_TOGGLE = 'HTML2IMAGE_TOGGLE_ENV_VAR_LOOKUP'

EDGE_EXECUTABLE_ENV_VAR_CANDIDATES = [
    'HTML2IMAGE_EDGE_BIN',
    'HTML2IMAGE_EDGE_EXE',
    'EDGE_BIN',
    'EDGE_EXE',
]


def _find_edge(user_given_executable=None):
    """ Finds a edge executable.

    Search Edge on a given path. If no path given,
    try to find Edge or Chromium-browser on a Windows or Unix system.

    Parameters
    ----------
    - `user_given_executable`: str (optional)
        + A filepath leading to a Edge executable
        + Or a filename found in the current working directory
        + Or a keyword that executes Edge/ Chromium, ex:
            - 'msedge' on linux and windows systems (typing `start msedge` in a windows cmd works)

    Raises
    ------
    - `FileNotFoundError`
        + If a suitable edge executable could not be found.

    Returns
    -------
    - str
        + Path of the edge executable on the current machine.
    """

    # try to find a edge bin/exe in ENV
    path_from_env = find_first_defined_env_var(
        env_var_list=EDGE_EXECUTABLE_ENV_VAR_CANDIDATES,
        toggle=ENV_VAR_LOOKUP_TOGGLE
    )

    if path_from_env:
        print(
            f'Found a potential edge executable in the {path_from_env} '
            f'environment variable:\n{path_from_env}\n'
        )
        return path_from_env

    # if an executable is given, try to use it
    if user_given_executable is not None:

        # On Windows, we cannot "safely" validate that user_given_executable
        # seems to be a edge executable, as we cannot run it with
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
        # user_given_executable leads to a Edge executable,
        # or is a command, using the --version flag
        else:
            try:
                if 'edge' in subprocess.check_output(
                    [user_given_executable, '--version']
                ).decode('utf-8').lower():
                    return user_given_executable
            except Exception:
                pass

        # We got a user_given_executable but couldn't validate it
        raise FileNotFoundError(
            'Failed to find a seemingly valid edge executable '
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

        suffix = "Microsoft\\Edge\\Application\\msedge.exe"

        for prefix in prefixes:
            path_candidate = os.path.join(prefix, suffix)
            if os.path.isfile(path_candidate):
                return path_candidate

    # Search for executable on a Linux OS
    elif platform.system() == "Linux":

        edge_commands = [
            'msedge',
            '/opt/microsoft/msedge/msedge'
        ]

        for edge_command in edge_commands:
            if shutil.which(edge_command):
                # check the --version for "edge" ?
                return edge_command

    # Search for executable on MacOS
    elif platform.system() == "Darwin":
        # MacOS system
        edge_app = (
            '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
        )

        try:
            version_result = subprocess.check_output(
                [edge_app, "--version"]
            )
            if "Microsoft Edge" in str(version_result):
                return edge_app
        except Exception:
            pass

    # Couldn't find an executable (or OS not in Windows, Linux or Mac)
    raise FileNotFoundError(
        'Could not find a Edge executable on this '
        'machine, please specify it yourself.'
    )

class EdgeHeadless(ChromiumHeadless):
    """
        Edge browser wrapper.

        Parameters
        ----------
        - `executable` : str, optional
            + Path to a edge executable.
        - `flags` : list of str
            + Flags to be used by the headless browser.
            + Default flags are :
                - '--default-background-color=00000000'
                - '--hide-scrollbars'
        - `print_command` : bool
            + Whether or not to print the command used to take a screenshot.
        - `disable_logging` : bool
            + Whether or not to disable Chrome's output.
        - `use_new_headless` : bool, optional
            + Whether or not to use the new headless mode.
            + By default, the old headless mode is used.
            + You can also keep the original behavior to backward compatibility by setting this to `None`.
    """

    def __init__(self, executable=None, flags=None, print_command=False, disable_logging=False, use_new_headless=None,):
        super().__init__(executable=executable, flags=flags, print_command=print_command, disable_logging=disable_logging, use_new_headless=use_new_headless)

    @property
    def executable(self):
        return self._executable

    @executable.setter
    def executable(self, value):
        self._executable = _find_edge(value)
