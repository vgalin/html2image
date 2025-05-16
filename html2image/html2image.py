"""
Main file of the html2image package.

html2image is a package acting as a wrapper around the
headless mode of existing web browsers to generate images
from URLs and from HTML+CSS strings or files.

For feedback, usage and to learn more, see https://github.com/vgalin/html2image
"""

import os
import shutil

from textwrap import dedent

from html2image.browsers import chrome, chrome_cdp, edge  # , firefox, firefox_cdp
from html2image.browsers.browser import Browser, CDPBrowser


browser_map = {
    'chrome': chrome.ChromeHeadless,
    'chromium': chrome.ChromeHeadless,
    'google-chrome': chrome.ChromeHeadless,
    'google-chrome-stable': chrome.ChromeHeadless,
    'googlechrome': chrome.ChromeHeadless,
    'edge': edge.EdgeHeadless,
    'chrome-cdp': chrome_cdp.ChromeCDP,
    'chromium-cdp': chrome_cdp.ChromeCDP,
    # 'firefox': firefox.FirefoxHeadless,
    # 'mozilla-firefox': firefox.FirefoxHeadless,
    # 'firefox-cdp': firefox_cdp.FirefoxCDP,
}


class Html2Image():
    """
        Allows the generation of images from
        URLs and HTML/CSS files or strings.

        Parameters
        ----------
        - `browser`: str , optional
            + Type of the browser that will be used to take screenshots.
            + Default is Chrome.

        - `browser_executable` : str, optional
            + Path to a browser executable.

        - `output_path` : str, optional
            + Path to a directory in which the taken screenshots will be saved.
            + Default is the current working directory.

        - `size` : (int, int), optional
            + Size of the screenshots.
            + Default is (1920, 1080).

        - `temp_path` : str, optional
            + Path to a directory that will be used to store temporary files.

        - `keep_temp_files` : bool, optional
            + If True, will not automatically remove temporary files created.

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
        browser_executable=None,
        browser_cdp_port=None,
        output_path=os.getcwd(),
        size=(1920, 1080),
        temp_path=None,
        keep_temp_files=False,
        custom_flags=None,
        disable_logging=False,
    ):

        if browser.lower() not in browser_map:
            raise ValueError(
                f'"{browser}" is not a browser known by HTML2Image.'
            )

        self.output_path = output_path
        self.size = size
        self.temp_path = temp_path
        self.keep_temp_files = keep_temp_files
        self.browser: Browser = None

        browser_class = browser_map[browser.lower()]

        if isinstance(browser_class, CDPBrowser):
            self.browser = browser_class(
                executable=browser_executable,
                flags=custom_flags,
                cdp_port=browser_cdp_port,
                disable_logging=disable_logging,
            )
        else:
            self.browser = browser_class(
                executable=browser_executable,
                flags=custom_flags,
                disable_logging=disable_logging,
            )

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

    def _remove_temp_file(self, filename):
        """ Removes a file in the tmp directory.

        This function is used after a temporary file is created in order to
        load an HTML string.
        This prevents the temp directory to end up bloated by temp files.

        Parameters
        ----------
        - `filename`: str
            + Filename of the file to be removed
            + (path is the temp_path directory)
        """
        os.remove(os.path.join(self.temp_path, filename))

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

        self.browser.screenshot(
            output_path=self.output_path,
            output_file=output_file,
            input=file,
            size=size,
        )

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

        self.browser.screenshot(
            output_path=self.output_path,
            output_file=output_file,
            input=url,
            size=size
        )

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
    def _prepare_html_string(html_body, css_style_string) -> str:
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
          <meta charset="UTF-8">
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

    @staticmethod
    def _prepare_css_string(css_file: list[str])-> str:
        """ Creates a basic string fromatted from a list of css files.

        Parameters
        ----------
        - `css_file`: str

        Returns
        -------
        - str
            The concatenated content of each css files.

        """

        css_str = ''
        for css in css_file:
            temp_css_str = ''
            with open(css, "r") as fd:
                temp_css_str = fd.read()
                css_str += temp_css_str + '\n'

        return css_str


    def screenshot(
        self,
        html_str=[],  # html_str: Union[str, list] = [],
        html_file=[],
        css_str=[],
        css_file=[],
        other_file=[],
        url=[],
        save_as='screenshot.png',
        size=[],
    ):
        """ Takes a screenshot using different resources.

        Parameters
        ----------
        - `html_str`: list of str or str
            + HTML string(s) that will be screenshotted.
        - `html_file`: list of str or str
            + Filepath(s) of HTML file(s) that will be screenshotted.
        - `css_str`: list of str or str
            + CSS string(s) that will be "associated" with the given
            + HTML string(s).
        - `css_file`: list of str or str
            + Filepath(s) of CSS file(s). These files serve two purposes:
            +   1. Their content is combined with `css_str` and embedded
            +      directly when screenshotting `html_str` (HTML strings).
            +   2. They are loaded into the temporary directory, making
            +      them available to `html_file` (HTML files) that link to them
            +      (e.g., via `<link rel="stylesheet" href="filename.css">`).
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
        html_strings = [html_str] if isinstance(html_str, str) else html_str
        html_files = [html_file] if isinstance(html_file, str) else html_file
        css_strings = [css_str] if isinstance(css_str, str) else css_str
        css_files = [css_file] if isinstance(css_file, str) else css_file
        other_files = [other_file] if isinstance(other_file, str) else other_file
        urls = [url] if isinstance(url, str) else url
        save_as_filenames = [save_as] if isinstance(save_as, str) else save_as
        sizes = [size] if isinstance(size, tuple) else size

        planned_screenshot_count = (
            len(html_strings) + len(html_files) + len(other_files) + len(urls)
        )
        save_as_filenames = Html2Image._extend_save_as_param(
            save_as_filenames,
            planned_screenshot_count,
        )
        sizes = self._extend_size_param(sizes, planned_screenshot_count)

        css_style_string = '\n'.join(css_strings) + '\n'

        if css_files:
            # add content from css_files, regardless of whether css_strings was present
            css_style_string += Html2Image._prepare_css_string(css_files)


        for css in css_files:
            if os.path.isfile(css):
                self.load_file(src=css)
            else:
                raise FileNotFoundError(css)

        for html in html_strings:
            name = save_as_filenames.pop(0)
            current_size = sizes.pop(0)

            base_name, _ = os.path.splitext(name)
            html_filename = base_name + '.html'

            content = Html2Image._prepare_html_string(html, css_style_string)

            self.load_str(content=content, as_filename=html_filename)
            self.screenshot_loaded_file(
                file=html_filename,
                output_file=name,
                size=current_size,
            )
            if not self.keep_temp_files:
                self._remove_temp_file(html_filename)

            screenshot_paths.append(os.path.join(self.output_path, name))

        for screenshot_target in html_files + other_files:

            name = save_as_filenames.pop(0)
            current_size = sizes.pop(0)

            if os.path.isfile(screenshot_target):
                self.load_file(src=screenshot_target)
                self.screenshot_loaded_file(
                    file=os.path.basename(screenshot_target),
                    output_file=name,
                    size=current_size,
                )
                if not self.keep_temp_files:
                    self._remove_temp_file(os.path.basename(screenshot_target))                
            else:
                raise FileNotFoundError(screenshot_target)

            screenshot_paths.append(os.path.join(self.output_path, name))

        for target_url in urls:
            name = save_as_filenames.pop(0)
            current_size = sizes.pop(0)

            self.screenshot_url(
                url=target_url,
                output_file=name,
                size=current_size,
            )
            screenshot_paths.append(os.path.join(self.output_path, name))

        return screenshot_paths

    def __enter__(self):
        self.browser.__enter__()
        return self

    def __exit__(self, *exc):
        self.browser.__exit__(*exc)


if __name__ == '__main__':
    pass
