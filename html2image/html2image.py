"""
Main file of the html2image package.

html2image ia a package acting as a wrapper around the
headless mode of existing web browsers to generate images
from URLs and from HTML+CSS strings or files.

For feedback, usage and to learn more, see https://github.com/vgalin/html2image
"""

import os
import platform
import shutil
import subprocess

from textwrap import dedent


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


class Html2Image():
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

        - `custom_flags`: list of str or str, optional
            + Additional custom flags for the headless browser.

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
        custom_flags=[],
        print_command=False
    ):

        self.browser = browser
        self.output_path = output_path
        self.size = size
        self.temp_path = temp_path
        self.print_command = print_command
        self.custom_flags = (
            [custom_flags] if isinstance(custom_flags, str) else custom_flags
        )

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

    def _chrome_render(
        self, output_file='render.png', input_file='', size=None
    ):
        """ Calls Chrome or Chromium headless to take a screenshot.

            Parameters
            ----------
            - `output_file`: str
                + Name as which the screenshot will be saved.
                + File extension (e.g. .png) has to be included.
                + Default is screenshot.png
            - `input_file`: str
                + File (or url...) that will be screenshotted.
            - `size`: (int, int), optional
                + Two values representing the window size of the headless
                + browser and by extention, the screenshot size.
                + These two values must be greater than 0.
            Raises
            ------
            - `ValueError`
                + If the value of `size` is incorrect.
        """

        if size is None:
            size = self.size

        if size[0] < 1 or size[1] < 1:
            raise ValueError(
                f'Could not screenshot "{output_file}" '
                f'with a size of {size}:\n'
                'A valid size consists of two integer greater than 0.'
            )

        # command used to launch chrome in
        # headless mode and take a screenshot
        command = [
            f'{self.chrome_path}',
            '--headless',
            f'--screenshot={os.path.join(self.output_path, output_file)}',
            f'--window-size={size[0]},{size[1]}',
            '--default-background-color=0',
            '--hide-scrollbars',
            # TODO : make it possible to choose to display the scrollbar or not
            *self.custom_flags,
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
        `temp_path` attribute.

        Parameters
        ----------
        - `content`: str
            + HTML/CSS formatted text.

        - `as_filename`: str
            + Filename as which the given string will be saved.

        """
        with open(os.path.join(self.temp_path, as_filename), 'wb') as f:
            f.write(content.encode('utf-8'))

    def load_file(self, src, as_filename=None):
        """ 'Loads' a file that html2image can use later to take a screenshot.

        Behind the scenes, the file found at `src` is:
        -   eventually renamed, if the `as_filename` parameter is specified;
        -   then sent to the directory defined in the  `temp_path` attribute.

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

    def screenshot_loaded_file(
        self, file, output_file='screenshot.png', size=None
    ):
        """ Takes a screenshot of a *previously loaded* file or string.

        Parameters
        ----------
        - `file`: str
            + HTML file that will be screenshotted.

        - `output_file`: str
            + Name as which the screenshot will be saved.
            + File extension (e.g. .png) has to be included.
            + Default is screenshot.png

        - `size`: (int, int), optional
            + Size of the screenshot that will be taken when the
            method is called.
        """

        file = os.path.join(self.temp_path, file)

        if os.path.dirname(output_file) != '':
            raise ValueError(
                "the output_file parameter should be a filename "
                "and not a path.\nChange the output path by "
                "modifying the output_path attribute."
            )

        self._render(output_file=output_file, input_file=file, size=size)

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

        - `size`: (int, int), optional
            + Size of the screenshot that will be taken when the
            + method is called.
        """

        if os.path.dirname(output_file) != '':
            raise ValueError(
                "the output_file parameter should be a filename "
                "and not a path.\nChange the output path by "
                "modifying the output_path attribute."
            )

        self._render(input_file=url, output_file=output_file, size=size)

    @staticmethod
    def _extend_save_as_param(save_as, desired_length):
        """ Extend the save_as parameter of the `screenshot()` method.

        So we do not run out of filenames.

        Parameters
        ----------
        - `save_as`: list
            + List of filenames
        - `desired_length`: int
            + Minimum desired length of the ouput

        Returns
        -------
        - list
            + `save_as` extended to `desired_length`

        Examples
        --------
        >>> _extend_save_as_param(['a.png', 'b.png'], 2)
        ['a.png', 'b.png']

        >>> _extend_save_as_param(['a.png', 'b.png'], 4)
        ['a.png', 'b_0.png', 'b_1.png', 'b_2.png']

        >>> _extend_save_as_param(['a.png', 'b.png'], 0)
        ['a.png', 'b.png']

        >>> _extend_save_as_param(['a.png', 'b.png', None, 65], 2)
        ['a.png', 'b.png']
        """

        # get rid of anything that is not a string
        save_as = [name for name in save_as if isinstance(name, str)]

        if desired_length <= len(save_as):
            return save_as

        missing_name_count = desired_length - len(save_as)
        filename, extention = save_as[-1].split('.')

        # remove last object as it will be replaced
        # from filename.extention to filename_0.extention
        save_as.pop()

        save_as.extend([
            f'{filename}_{i}.{extention}'
            for i in range(missing_name_count + 1)
        ])

        return save_as

    def _extend_size_param(self, sizes, desired_length):
        """ Extend the size parameter of the `screenshot()` method.

        So we do not run out of sizes.
        If the given the `sizes` parameter is an empty list, the list
        will the extended using `self.size`.

        Parameters
        ----------
        - `save_as`: list
            + List of (int, int) tuples
        - `desired_length`: int
            + Minimum desired length of the ouput

        Returns
        -------
        - list
            + `sizes` extended to `desired_length`

        Examples
        --------
        >>> _extend_size_param([(50, 50)], 1)
        [(50, 50)]

        >>> _extend_size_param([(50, 50)], 3)
        [(50, 50), (50, 50), (50, 50)]

        >>> _extend_size_param([(50, 50), (70, 60), (80, 90)], 5)
        [(50, 50), (70, 60), (80, 90), (80, 90), (80, 90)]

        >>> _extend_size_param([], 3)
        [(1920, 1080), (1920, 1080), (1920, 1080)]

        """

        # get rid of anything that is not a string
        sizes = [
            size for size in sizes
            if isinstance(size, tuple) and len(size) == 2
        ]

        if desired_length <= len(sizes):
            return sizes

        # if no size specified, then use default size
        if len(sizes) == 0:
            return [
                self.size
                for i in range(desired_length)
            ]

        missing_size_count = desired_length - len(sizes)
        last_size = sizes[-1]

        sizes.extend([
            last_size
            for i in range(missing_size_count)
        ])

        return sizes

    @staticmethod
    def _prepare_html_string(html_body, css_style_string):
        """ Creates a basic HTML string from an HTML body and a css string.

        Parameters
        ----------
        - `html_body`: str
        - `css_style_string`: str

        Returns
        -------
        - str
            A combination of `html_body` and `css_style_string` put
            together in an HTML template.

        """

        prepared_html = f"""\
        <html>
        <head>
            <style>
                {css_style_string}
            </style>
        </head>

        <body>
            {html_body}
        </body>
        </html>
        """
        return dedent(prepared_html)

    def screenshot(
        self,
        html_str=[],  # html_str: Union[str, list] = [],
        html_file=[],
        css_str=[],
        css_file=[],
        other_file=[],
        url=[],
        save_as='screenshot.png',
        size=[]
    ):
        """ Takes a screeshot using different resources.

        Parameters
        ----------
        - `html_str`: list of str or str
            + HTML string(s) that will be screenshotted.
        - `html_file`: list of str or str
            + Filepath(s) of HTML file(s) that will be screenshotted.
        - `css_str`: list of str or str
            + CSS string(s) that will be "associated" with the given
            + HTML string(s)
        - `css_file`: list of str or str
            + CSS file(s) supposedly already mentionned by their filenames
            + in the content of the `html_file`(s).
        - `other_file`: list of str or str
            + Filepath(s) of non-HTML file(s) that will be screenshotted.
        - `url`: list of str or str
            + URL(s) of the page(s) that will be screenshotted.
            + Do not ommit the protocol.
        - `save_as`: list of str or str
            + Name(s) as which the screenshot will be saved.
            + File extension (e.g. .png) has to be included.
            + Default value is screenshot.png
        - `size`: list of (int, int) or (int, int) tuple
            + Size(s) of the screenshot(s) that will be taken when the
            + method is called.

        Returns
        -------
        - list of str
            + A list of the file path(s) of the generated image(s)

        Raises
        ------
        - `FileNotFoundError`
        """

        # TODO / NOTE : This does not pose any problem for now but setting
        # mutables (here empty lists) as default arguments of a function
        # can cause unwanted behaviours.

        screenshot_paths = []

        # convert each parameter into list
        # e.g: param=value becomes param=[value]
        html_str = [html_str] if isinstance(html_str, str) else html_str
        html_file = [html_file] if isinstance(html_file, str) else html_file
        css_str = [css_str] if isinstance(css_str, str) else css_str
        css_file = [css_file] if isinstance(css_file, str) else css_file
        other_file = (
            [other_file] if isinstance(other_file, str) else other_file
        )
        url = [url] if isinstance(url, str) else url
        save_as = [save_as] if isinstance(save_as, str) else save_as
        size = [size] if isinstance(size, tuple) else size

        planned_screenshot_count = (
            len(html_str) + len(html_file) + len(other_file) + len(url)
        )
        save_as = Html2Image._extend_save_as_param(
            save_as,
            planned_screenshot_count,
        )
        size = self._extend_size_param(size, planned_screenshot_count)

        css_style_string = ""

        for css in css_str:
            css_style_string += css + '\n'

        for css in css_file:
            if os.path.isfile(css):
                self.load_file(src=css)
            else:
                raise FileNotFoundError(css)

        for html in html_str:
            name = save_as.pop(0)
            current_size = size.pop(0)

            html_filename = name.split('.')[0] + '.html'
            content = Html2Image._prepare_html_string(
                html, css_style_string
            )
            self.load_str(content=content, as_filename=html_filename)
            self.screenshot_loaded_file(
                file=html_filename,
                output_file=name,
                size=current_size,
            )

            screenshot_paths.append(os.path.join(self.output_path, name))

        for screenshot_target in html_file + other_file:

            name = save_as.pop(0)
            current_size = size.pop(0)

            if os.path.isfile(screenshot_target):
                self.load_file(src=screenshot_target)
                self.screenshot_loaded_file(
                    file=os.path.basename(screenshot_target),
                    output_file=name,
                    size=current_size,
                )
            else:
                raise FileNotFoundError(screenshot_target)

            screenshot_paths.append(os.path.join(self.output_path, name))

        for target_url in url:
            name = save_as.pop(0)
            current_size = size.pop(0)

            self.screenshot_url(
                url=target_url,
                output_file=name,
                size=current_size,
            )
            screenshot_paths.append(os.path.join(self.output_path, name))

        return screenshot_paths


if __name__ == '__main__':
    pass
