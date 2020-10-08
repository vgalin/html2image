"""
Main file of the html2image package.

html2image ia a package acting as a wrapper around the
headless mode of existing web browsers to generate images
from URLs and from HTML+CSS strings or files.

For usage and to learn more, see https://github.com/vgalin/html2imag
"""

import os
import platform
import shutil
import subprocess


def _find_chrome(user_given_path=None):
    """ Finds a Chrome executable.

    Search Chrome on a given path. If no path given,
    try to find Chrome or Chromium-browser on a Windows or Unix system.

    Raises
    ------
    - `FileNotFoundError`
        + If a suitable chrome executable could not be found.
    """

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
        # snap seems to be a special case?
        # see https://stackoverflow.com/q/63375327/12182226
        version_result = subprocess.check_output(
            ["chromium-browser", "--version"]
        )
        if 'snap' in str(version_result):
            chrome_snap = '/snap/chromium/current/usr/lib/chromium-browser/chrome'
            if os.path.isfile(chrome_snap):
                return chrome_snap
        else:
            # search for chromium-browser with a python
            # equivalent of the `which` command
            which_result = shutil.which('chromium-browser')
            if which_result is not None and os.path.isfile(which_result):
                return which_result

    elif platform.system() == "Darwin":
        # MacOS system
        chrome_app = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        version_result = subprocess.check_output(
            [chrome_app, "--version"]
        )
        if "Google Chrome" in str(version_result):
            return chrome_app

    raise FileNotFoundError(
        'Could not find a Chrome executable on this '
        'machine, please specify it yourself.'
    )


class HtmlToImage():
    """
        Allows the generation of images from
        URLs and HTML/CSS files or strings.

        Parameters
        ----------
        - `browser`: str , optional
            + Type of the browser that will be used to take screenshots.
            + Default is Chrome.

        - `chrome_path` : str, optional
            + Path to a Chrome/Chromium executable.

        - `firefox_path` : str, optional
            + Path to a Firefox executable.

        - `output_path` : str, optional
            + Path to a directory in which the taken screenshots will be saved.
            + Default is the current working directory.

        - `size` : (int, int), optional
            + Size of the screenshots.
            + Default is (1920, 1080).

        - `temp_path` : str, optional
            + Path to a directory that will be used to store temporary files.

        Raises
        ------
        - `FileNotFoundError`
            + If an executable of the browser specified in the `browser`
            parameter was not found.
    """

    def __init__(
        self,
        browser='chrome',
        chrome_path=None,
        firefox_path=None,
        output_path=os.getcwd(),
        size=(1920, 1080),
        temp_path=None,
        print_command=False
    ):

        self.browser = browser
        self.output_path = output_path
        self.size = size
        self.temp_path = temp_path
        self.print_command = print_command

        # TODO : add @property + setter on self.browser to do the following
        if self.browser == "chrome":
            self._render = self._chrome_render
            self.chrome_path = chrome_path

        elif self.browser == "firefox":
            raise NotImplementedError
        else:
            raise NotImplementedError

    @property
    def chrome_path(self):
        return self._chrome_path

    @chrome_path.setter
    def chrome_path(self, value):
        self._chrome_path = _find_chrome(value)

    @property
    def temp_path(self):
        return self._temp_path

    @temp_path.setter
    def temp_path(self, value):
        if value is None:
            temp_dir = os.environ['TMP'] if os.name == 'nt' else '/tmp'
            temp_dir = os.path.join(temp_dir, 'html2image')
        else:
            temp_dir = value

        # create the directory if it does not exist
        os.makedirs(temp_dir, exist_ok=True)

        self._temp_path = temp_dir

    @property
    def output_path(self):
        return self._output_path

    @output_path.setter
    def output_path(self, value):
        # output_path should always be an absolute path
        value = os.path.abspath(value)

        # create the directory if it does not exist
        os.makedirs(value, exist_ok=True)

        self._output_path = value

    def _chrome_render(self, output_file='render.png', input_file=''):
        """ Calls Chrome or Chromium headless to take a screenshot.

            Parameters
            ----------
            - `output_file`: str
                + Name as which the screenshot will be saved.
                + File extension (e.g. .png) has to be included.
                + Default is screenshot.png
            - `input_file`: str
                + File (or url...) that will be screenshotted.
        """

        # command used to launch chrome in
        # headless mode and take a screenshot
        command = [
            f'{self.chrome_path}',
            f'--headless',
            f'--screenshot={os.path.join(self.output_path, output_file)}',
            f'--window-size={self.size[0]},{self.size[1]}',
            f'--default-background-color=0',
            f'--hide-scrollbars',
            # TODO : make it possible to choose to display the scrollbar or not
            f'{input_file}',
        ]

        if self.print_command:
            print(command)
            print()

        subprocess.run(command)

    def _firefox_render(self, output_file='render.png', input_file=''):
        """ Not implemented.
        """
        raise NotImplementedError

    def load_str(self, content, as_filename):
        """
        Loads a string containing HTML or CSS so that html2image can use it
        later to take a screenshot.

        Behind the scenes the string (that can really contain anything) is
        written into a file that is saved in the directory defined in the
        `temp_dir` attribute.

        Parameters
        ----------
        - `content`: str
            + HTML/CSS formatted text.

        - `as_filename`: str
            + Filename as which the given string will be saved.

        """
        with open(os.path.join(self.temp_path, as_filename), 'w') as f:
            f.writelines(content)

    def load_file(self, src, as_filename=None):
        """ 'Loads' a file that html2image can use later to take a screenshot.

        Behind the scenes, the file found ad `src` is:
            eventually renamed, if the `as_filename` parameter is specified;
            then sent to the directory defined in the  `temp_dir` attribute.

        Parameters
        ----------
        - `src`: str
            + Path to the file to load.

        - `as_filename`: str
            + Filename as which the given file will renamed.
            + If None or not specified, the given file will keep
            its original name.
        """
        if as_filename is None:
            as_filename = os.path.basename(src)

        dest = os.path.join(self.temp_path, as_filename)
        shutil.copyfile(src, dest)

    def screenshot(self, file, output_file='screenshot.png', size=None):
        """ Takes a screenshot of a _previously loaded_ file or string.

        Parameters
        ----------
        - `file`: str
            + HTML file that will be screenshotted.

        - `output_file`: str
            + Name as which the screenshot will be saved.
            + File extension (e.g. .png) has to be included.
            + Default is screenshot.png

        - `size`: str, optional
            + Size of the screenshot that will be taken when the
            method is called. Also changes the size for future screenshots.
        """

        if size is not None:
            self.size = size

        file = os.path.join(self.temp_path, file)

        if os.path.dirname(output_file) != '':
            raise ValueError(
                "the output_file parameter should be a filename "
                "and not a path.\nChange the output path by "
                "modifying the output_path attribute."
            )

        self._render(output_file=output_file, input_file=file)

    def screenshot_url(self, url, output_file='screenshot.png', size=None):
        """ Takes a screenshot of a given URL.

        The given URL should be well formed or it may result in undefined
        behaviors when an headless browser will open it.
        Please do include the protocol in the URL (http, https).
        E.g. url = 'https://www.python.org/'

        Parameters
        ----------
        - `url`: str
            + URL of the page that will be screenshotted.
            + Do not ommit the protocol.

        - `output_file`: str, optional
            + Name as which the screenshot will be saved.
            + File extension (e.g. .png) has to be included.
            + Default is screenshot.png

        - `size`: str, optional
            + Size of the screenshot that will be taken when the
            + method is called. Also changes the size for future screenshots.
        """

        if size is not None:
            self.size = size

        if os.path.dirname(output_file) != '':
            raise ValueError(
                "the output_file parameter should be a filename "
                "and not a path.\nChange the output path by "
                "modifying the output_path attribute."
            )

        self._render(input_file=url, output_file=output_file)


if __name__ == '__main__':
    pass
