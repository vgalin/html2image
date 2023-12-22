import os
import platform
import shutil
import subprocess

try:
    from winreg import ConnectRegistry, OpenKey, QueryValueEx,\
            HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER, KEY_READ
except ImportError:
    # os is not Windows, and there is no need for winreg
    pass

ENV_VAR_LOOKUP_TOGGLE = 'HTML2IMAGE_TOGGLE_ENV_VAR_LOOKUP'

CHROME_EXECUTABLE_ENV_VAR_CANDIDATES = [
    'HTML2IMAGE_CHROME_BIN',
    'HTML2IMAGE_CHROME_EXE',
    'CHROME_BIN',
    'CHROME_EXE',
]

FIREFOX_EXECUTABLE_ENV_VAR_CANDIDATES = [
    'HTML2IMAGE_FIREFOX_BIN',
    'HTML2IMAGE_FIREFOX_EXE',
    'FIREFOX_BIN',
    'FIREFOX_EXE',
]


def get_command_origin(command):
    ''' Finds the path of a given command (windows only).

    This function is inspired by the `start` command on windows.
    It will search if the given command corresponds :
    - To an executable in the current directory
    - To an executable in the PATH environment variable
    - To an executable mentionned in the registry in the
      HKEY_LOCAL_MACHINE or HKEY_LOCAL_MACHINE hkeys in
      SOFTWARE\\[Wow6432Node\\]Microsoft\\Windows\\CurrentVersion\\App Paths\\

    It also "indirectly" validates a path to a file.

    Parameters
    ----------
    - `command`: str
        + command that will be searched.

    Returns
    -------
    - str or None
        + the path corresponding to `command`
        + None, if no path was found
    '''

    # `start "command"` itself could be used to run the command but we want to
    # assess that the command is a valid one.
    command = command.replace('start ', '')

    # which search in current directory + path
    # and file extention can be ommited
    which_result = shutil.which(command)
    if which_result:
        return which_result

    # search for command in registry

    command = command.replace('.exe', '').strip()

    # Once combined, these hkeys and keys are where the `start`
    # command seach for executable.
    hkeys = [HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER]
    keys = [
        "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\"
        f"App Paths\\{command}.exe",

        "SOFTWARE\\Wow6432Node\\Microsoft\\Windows\\"
        "CurrentVersion\\App Paths\\"
        f"{command}.exe",
    ]

    for hkey in hkeys:
        with ConnectRegistry(None, hkey) as registry:
            for key in keys:
                try:
                    with OpenKey(registry, key, 0, KEY_READ) as k:
                        # if no exception: we found the exe
                        return QueryValueEx(k, '')[0]
                except Exception:
                    # cannot open key, do nothing and proceed to the next one
                    pass
    return None


def find_first_defined_env_var(env_var_list, toggle):
    '''
    Returns the value of the first defined environment variable
    encountered in the `env_var_list` list, but only if the
    the `toggle` environment variableif defined.

    Parameters
    ----------
    - `env_var_list`: list[str]
        + list of environment variable names
    - `toggle`: str
        + environment variable name


    '''
    if toggle in os.environ:
        for env_var in env_var_list:
            value = os.environ.get(env_var)
            if value:
                return value
    return None


def find_chrome(user_given_executable=None):
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
            'google-chrome',
            'google-chrome-stable'
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

def find_firefox(user_given_executable=None):
    """ Finds a Firefox executable.

    Search Firefox on a given path. If no path given,
    try to find Firefox on a Windows or Unix system.

    Parameters
    ----------
    - `user_given_executable`: str (optional)
        + A filepath leading to a Firefox executable
        + Or a filename found in the current working directory
        + Or a keyword that executes Firefox, ex:
            - 'firefox' on linux systems
            - 'firefox' on windows (if typing `start firefox` in a cmd works)

    Raises
    ------
    - `FileNotFoundError`
        + If a suitable Firefox executable could not be found.

    Returns
    -------
    - str
        + Path of the Firefox executable on the current machine.
    """

    # try to find a firefox bin/exe in ENV
    path_from_env = find_first_defined_env_var(
        env_var_list=FIREFOX_EXECUTABLE_ENV_VAR_CANDIDATES,
        toggle=ENV_VAR_LOOKUP_TOGGLE
    )

    if path_from_env:
        print(
            f'Found a potential Firefox executable in the {path_from_env} '
            f'environment variable:\n{path_from_env}\n'
        )
        return path_from_env

    # if an executable is given, try to use it
    if user_given_executable is not None:

        if platform.system() == 'Windows':
            user_given_executable = get_command_origin(user_given_executable)

        try:
            version_output = subprocess.check_output(
                [user_given_executable, '--version']
            ).decode('utf-8').lower()

            if 'Mozilla Firefox' in version_output:
                return user_given_executable
            else:
                print(
                    'Could not validate Firefox executable',
                    '(--version does not contains "Mozilla Firefox").'
                )
        except Exception:
            pass

        # We got a user_given_executable but couldn't validate it
        raise FileNotFoundError(
            'Failed to find a seemingly valid Firefox executable '
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

        suffix = 'Mozilla Firefox\\firefox.exe'

        for prefix in prefixes:
            path_candidate = os.path.join(prefix, suffix)
            if os.path.isfile(path_candidate):
                return path_candidate

    # Search for executable on a Linux OS
    elif platform.system() == 'Linux':
        if shutil.which('firefox'):
            return 'firefox'

    # Search for executable on MacOS
    elif platform.system() == 'Darwin':
        # MacOS system

        # TODO : check if this is the right path
        firefox_app = (
            '/Applications/Firefox.app/Contents/MacOS/firefox'  # ?
        )

        try:
            version_result = subprocess.check_output(
                [firefox_app, '--version']
            )
            if 'Mozilla Firefox' in str(version_result):
                return firefox_app
        except Exception:
            pass

    # Couldn't find an executable (or OS not in Windows, Linux or Mac)
    raise FileNotFoundError(
        'Could not find a Chrome executable on this '
        'machine, please specify it yourself.'
    )
