import shutil
import os
try:
    from winreg import ConnectRegistry, OpenKey, QueryValueEx,\
            HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER, KEY_READ
except ImportError:
    # os is not Windows, and there is no need for winreg
    pass


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
