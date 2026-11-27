"""
Main file of the html2image package.

html2image is a package acting as a wrapper around the
headless mode of existing web browsers to generate images
from URLs and from HTML+CSS strings or files.

For feedback, usage and to learn more, see https://github.com/vgalin/html2image
"""

import contextlib
import os
import re
import shutil
import tempfile
import threading

from textwrap import dedent
from typing import List

from html2image.browsers import chrome, chrome_cdp, edge, edge_cdp, firefox, firefox_bidi
from html2image.browsers import _page_fit_common as page_fit
from html2image.browsers.browser import Browser, CDPBrowser, BiDiBrowser
from html2image.exceptions import CaptureTooLargeError, ElementNotFoundError


browser_map = {
    # Chrome/Chromium - default to the CDP backend for correct viewport rendering.
    # Use 'chrome-headless' to get the legacy CLI (--screenshot) path if needed.
    'chrome': chrome_cdp.ChromeCDP,
    'chromium': chrome_cdp.ChromeCDP,
    'google-chrome': chrome_cdp.ChromeCDP,
    'google-chrome-stable': chrome_cdp.ChromeCDP,
    'googlechrome': chrome_cdp.ChromeCDP,
    'chrome-headless': chrome.ChromeHeadless,   # legacy CLI path
    'edge': edge_cdp.EdgeCDP,
    'edge-cdp': edge_cdp.EdgeCDP,
    'edge-headless': edge.EdgeHeadless,
    'chrome-cdp': chrome_cdp.ChromeCDP,
    'chromium-cdp': chrome_cdp.ChromeCDP,
    # Firefox
    'firefox': firefox_bidi.FirefoxBiDi,
    'mozilla-firefox': firefox_bidi.FirefoxBiDi,
    'firefox-bidi': firefox_bidi.FirefoxBiDi,
    'firefox-headless': firefox.FirefoxHeadlessScreenshot,
}

# Paper sizes of the `pdf()` method, in their own orientation.
paper_sizes = {
    'a3': ('297mm', '420mm'),
    'a4': ('210mm', '297mm'),
    'a5': ('148mm', '210mm'),
    'letter': ('8.5in', '11in'),
    'legal': ('8.5in', '14in'),
    'tabloid': ('11in', '17in'),
    # Default size of a 16:9 PowerPoint slide.
    'slide': ('1280px', '720px'),
}

# Absolute CSS units, as the number of units in one inch.
css_units = {
    'mm': 25.4,
    'cm': 2.54,
    'q': 101.6,
    'in': 1,
    'pt': 72,
    'pc': 6,
    'px': 96,
}

# Held while a file is loaded under its own name, see `_load_shared_file()`,
# and while a temporary file is taken or given back, see `_temp_file()`.
# Objects may share their `temp_path`, as they do by default.
_shared_file_lock = threading.Lock()

# Paths of the temporary files of the pages being captured, in lower case.
_temp_files_in_use = set()


class Html2Image():
    """
        Allows the generation of images from
        URLs and HTML/CSS files or strings.

        Parameters
        ----------
        - `browser`: str , optional
            + Type of the browser that will be used to take screenshots.
            + Default is ``'chrome'``, which uses the Chrome DevTools Protocol
              (CDP) backend for pixel-accurate screenshots.
            + Use ``'chrome-headless'`` for the legacy ``--screenshot`` CLI path
              (faster startup, but viewport-filling content such as ``100vh``
              may show a blank strip at the bottom due to a Chrome limitation).

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
            + Flags for the headless browser. They will replace its default
              flags, such as ``--hide-scrollbars``.
            + On Windows, the ``'chrome'`` and ``'edge'`` browsers will also
              be started with ``--disable-skia-graphite``, which keeps
              screenshots fast with a graphics card. This flag will not be
              added if ``custom_flags`` holds ``--enable-skia-graphite``.

        - `allow_scripts_to_read_files` : bool, optional
            + Lets JavaScript in HTML opened from a file read other files on
              disk, for example with `fetch()`. Images, stylesheets and fonts
              load without it, unless their tag has a `crossorigin` attribute.
            + Security risk: any script in the page can then read any file the
              current user can read and send it over the network. Only enable
              it for HTML you trust.
            + Default is False.

        - `add_doctype` : bool, optional
            + If True, pages built from `html_str` start with
              `<!DOCTYPE html>`, so browsers render them like any modern
              web page.
            + If False, the doctype is left out, as in html2image 2.x:
              browsers then use an old compatibility mode, which changes
              some layouts.
            + Default is True.

        - `max_concurrency` : int, optional
            + Maximum number of screenshots or PDFs that can be made at
              the same time, from several threads. Each one will use
              its own browser window.
            + Only works with the 'chrome' and 'edge' browsers, inside a
              `with` block. Outside one, each call will start and close
              the browser, and the calls will run one after the other.
            + A list given to a single call will still be captured one
              page after the other.
            + Default is 1.

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
        browser_bidi_port=None,
        output_path=os.getcwd(),
        size=(1920, 1080),
        temp_path=None,
        keep_temp_files=False,
        custom_flags=None,
        disable_logging=False,
        allow_scripts_to_read_files=False,
        add_doctype=True,
        max_concurrency=1,
    ):

        if browser.lower() not in browser_map:
            raise ValueError(
                f'"{browser}" is not a browser known by HTML2Image.'
            )

        self.output_path = output_path
        self.size = size
        self.temp_path = temp_path
        self.keep_temp_files = keep_temp_files
        self.add_doctype = add_doctype
        self.browser: Browser = None

        browser_class = browser_map[browser.lower()]

        if max_concurrency != 1 and not issubclass(browser_class, CDPBrowser):
            raise ValueError(
                'max_concurrency works with the "chrome" and "edge" browsers, '
                'not with "chrome-headless", "edge-headless", "firefox" or '
                '"firefox-headless".'
            )

        if issubclass(browser_class, CDPBrowser):
            cdp_kwargs = {}
            if browser_cdp_port is not None:
                cdp_kwargs['cdp_port'] = browser_cdp_port
            self.browser = browser_class(
                executable=browser_executable,
                flags=custom_flags,
                disable_logging=disable_logging,
                allow_scripts_to_read_files=allow_scripts_to_read_files,
                max_concurrency=max_concurrency,
                **cdp_kwargs,
            )
        elif issubclass(browser_class, BiDiBrowser):
            bidi_kwargs = {}
            if browser_bidi_port is not None:
                bidi_kwargs['bidi_port'] = browser_bidi_port
            self.browser = browser_class(
                executable=browser_executable,
                flags=custom_flags,
                disable_logging=disable_logging,
                allow_scripts_to_read_files=allow_scripts_to_read_files,
                **bidi_kwargs,
            )
        else:
            self.browser = browser_class(
                executable=browser_executable,
                flags=custom_flags,
                disable_logging=disable_logging,
                allow_scripts_to_read_files=allow_scripts_to_read_files,
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
        self._check_filename(as_filename)

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

        self._check_filename(as_filename)

        dest = os.path.join(self.temp_path, as_filename)
        shutil.copyfile(src, dest)

    @staticmethod
    def _check_filename(filename):
        """ Checks that a filename is not a path.

        This prevents files from being written outside of the
        directories defined in the `temp_path` and `output_path` attributes.

        Parameters
        ----------
        - `filename`: str
            + Filename to check.

        Raises
        ------
        - `ValueError`
            + If `filename` contains a directory.
        """
        if os.path.dirname(filename) != '':
            raise ValueError(
                f'"{filename}" should be a filename and not a path.'
            )

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
        try:
            os.remove(os.path.join(self.temp_path, filename))
        except FileNotFoundError:
            pass

    @contextlib.contextmanager
    def _temp_file(self, filename):
        """ Yields the name under which a page will be loaded in the
        `temp_path` directory, and removes the file at the end, unless
        `keep_temp_files` is set.

        The name is `filename`, unless a call in progress is using it.
        Then it is `filename` with a part that no other call will use, so
        that calls made at the same time never write the same file. The
        file stays in `temp_path`, so that a page can use the other files
        loaded there.
        """
        folder = os.path.realpath(self.temp_path)
        with _shared_file_lock:
            if os.path.join(folder, filename).lower() in _temp_files_in_use:
                name, extension = os.path.splitext(filename)
                handle, path = tempfile.mkstemp(
                    suffix=extension, prefix=name + '_', dir=folder,
                )
                os.close(handle)
                filename = os.path.basename(path)
            key = os.path.join(folder, filename).lower()
            _temp_files_in_use.add(key)
        try:
            yield filename
        finally:
            if not self.keep_temp_files:
                self._remove_temp_file(filename)
            with _shared_file_lock:
                _temp_files_in_use.discard(key)

    def _load_shared_file(self, src):
        """ Loads the file `src` under its own name, as `load_file()` does,
        unless the loaded file already has the same content.

        Pages use such a file by its name, so a page of another call may
        be reading it. It will only be written again if its content changed.
        """
        dest = os.path.join(self.temp_path, os.path.basename(src))
        with _shared_file_lock:
            if os.path.isfile(dest):
                with open(src, 'rb') as new, open(dest, 'rb') as loaded:
                    if new.read() == loaded.read():
                        return
            self.load_file(src=src)

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

    def _full_page_options(
        self, full_page, stability_timeout, profile, fixed_elements,
        max_pixels, save_as, size,
    ):
        """ Checks the full page options, see `screenshot()`.

        The names of the images and the sizes of the window are checked
        too, before any page is loaded.

        Returns
        -------
        - dict
            + The options to pass to the `screenshot()` method of the
            browser, or an empty dict if `full_page` is False.

        Raises
        ------
        - `ValueError`
            + If the browser cannot capture a full page, or if an option,
            a name or a size has an invalid value.
        """
        if not full_page:
            return {}

        if not isinstance(self.browser, (CDPBrowser, BiDiBrowser)):
            raise ValueError(
                'full_page works with the "chrome", "edge" and "firefox" '
                'browsers, not with "chrome-headless", "edge-headless" or '
                '"firefox-headless".'
            )

        page_fit.validate_stability_timeout(stability_timeout)
        if profile is not None:
            page_fit.validate_full_page_profile(profile)
        page_fit.validate_fixed_element_mode(fixed_elements)
        page_fit.validate_max_pixels(max_pixels)
        # The same names and sizes as those `_render()` will use.
        for name in [save_as] if isinstance(save_as, str) else save_as:
            if isinstance(name, str):
                page_fit.output_format_from_filename(name)
        sizes = [size] if isinstance(size, tuple) else size
        sizes = [pair for pair in sizes
                 if isinstance(pair, tuple) and len(pair) == 2]
        for width, height in sizes or [self.size]:
            page_fit.validate_viewport(width, height)

        return {
            'full_page': True,
            'full_page_stability_timeout': stability_timeout,
            'full_page_profile': profile,
            'full_page_fixed_elements': fixed_elements,
            'full_page_max_pixels': max_pixels,
        }

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
    def _prepare_html_string(html_body, css_style_string, add_doctype) -> str:
        """ Creates a basic HTML string from an HTML body and a css string.

        Parameters
        ----------
        - `html_body`: str
        - `css_style_string`: str
        - `add_doctype`: bool

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
        doctype = '<!DOCTYPE html>\n' if add_doctype else ''
        return doctype + dedent(prepared_html)

    @staticmethod
    def _prepare_css_string(css_file: List[str]) -> str:
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

    @staticmethod
    def _parse_css_length(length) -> float:
        """ Converts a length written as in CSS (e.g. '2cm') to inches.

        Only absolute units are accepted. A number without unit is only
        accepted if it is 0.

        Raises
        ------
        - `ValueError`
            + If `length` is not a valid length.
        """
        match = re.fullmatch(
            rf'(\d+\.?\d*|\.\d+)({"|".join(css_units)})?',
            str(length),
            re.IGNORECASE,
        )
        if not match or (not match[2] and float(match[1]) != 0):
            raise ValueError(
                f'"{length}" is not a valid length: use a number followed '
                'by mm, cm, Q, in, pt, pc or px, e.g. "1cm".'
            )

        number, unit = match.groups()
        return float(number) / css_units[unit.lower()] if unit else 0.0

    @staticmethod
    def _prepare_pdf_options(
        paper_size, landscape, margin, background, scale
    ) -> dict:
        """ Converts the options of the `pdf()` method for the browser.

        Returns
        -------
        - dict
            + The `width` and `height` of the paper and its `margin`
            (top, right, bottom, left), in inches, with `background`
            and `scale` unchanged.

        Raises
        ------
        - `ValueError`
            + If an option has an invalid value.
        """
        if not 0.1 <= scale <= 2:
            raise ValueError(
                f'scale should be between 0.1 and 2, got {scale}.'
            )

        if margin is None:
            margin = '0' if str(paper_size).lower() == 'slide' else '1cm'

        if isinstance(paper_size, str):
            if paper_size.lower() not in paper_sizes:
                raise ValueError(
                    f'"{paper_size}" is not a paper size known by HTML2Image.'
                )
            paper_size = paper_sizes[paper_size.lower()]

        width, height = (
            Html2Image._parse_css_length(length) for length in paper_size
        )
        if not width or not height:
            raise ValueError('The paper width and height should not be 0.')

        # The orientation is only given by the dimensions: browsers swap
        # them once more if they are also told the paper is in landscape.
        if landscape is not None:
            width, height = sorted((width, height), reverse=landscape)

        margins = [
            Html2Image._parse_css_length(length)
            for length in str(margin).split()
        ]
        if not 1 <= len(margins) <= 4:
            raise ValueError(
                f'margin should contain 1 to 4 lengths, got "{margin}".'
            )

        # As in CSS, a missing right or bottom margin is the top one,
        # and a missing left margin is the right one.
        for count, source in ((1, 0), (2, 0), (3, 1)):
            if len(margins) == count:
                margins.append(margins[source])

        top, right, bottom, left = margins
        if left + right >= width or top + bottom >= height:
            raise ValueError(
                f'margin "{margin}" leaves no room for content on the paper.'
            )

        return {
            'width': width,
            'height': height,
            'margin': tuple(margins),
            'background': background,
            'scale': scale,
        }

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
        selector=None,
        selector_padding=0,
        skip_missing=False,
        full_page=False,
        full_page_stability_timeout=None,
        full_page_profile=None,
        full_page_fixed_elements='auto',
        full_page_max_pixels=page_fit.DEFAULT_MAX_PIXELS,
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
            + With `selector`, give one name per image.
            + Default value is screenshot.png
        - `size`: list of (int, int) or (int, int) tuple
            + Size(s) of the screenshot(s) that will be taken when the
            + method is called.
            + With `selector`, this is the size of the window in which
            + each page will be displayed, with one size per page.
            + With `full_page=True`, the image will be as wide as `size`,
            + and as high as the page, but not less than the height of
            + `size`, which will be the height of the window.
        - `selector`: list of str or str, optional
            + CSS selector of an element, e.g. '#chart'. The image will
            + then show this element only, instead of the window, even if
            + the element is larger than the window or further down the
            + page.
            + If several elements match, the first one will be used, as
            + with `document.querySelector()` in JavaScript.
            + With a list, one image will be saved per selector, for each
            + page, and the images of the first page will come first.
            + Each page will only be loaded once, and each image will be
            + the same as with one call per selector, unless the page
            + changes when it is resized.
            + Only works with the 'chrome', 'edge' and 'firefox' browsers.
            + Default is None: the whole window will be captured. An
            + empty string or list will do the same.
        - `selector_padding`: int, optional
            + Number of pixels added around the element, to include its
            + shadow for example. The padding will stop at the edges of
            + the page.
            + Default is 0.
        - `skip_missing`: bool, optional
            + If True, missing elements will be skipped without raising
            + `ElementNotFoundError`, and the returned list will only
            + contain the saved images.
            + Default is False.
        - `full_page`: bool, optional
            + If True, the image will show the whole page, not only what
            + fits in the window.
            + Only works with the 'chrome', 'edge' and 'firefox' browsers.
            + Some pages will need `pyvips`, installed with
            + `pip install "html2image[full-page]"`.
            + Default is False.
        - `full_page_stability_timeout`: int, float or None, optional
            + The longest wait, in seconds, each time the height of the
            + page has to stop changing, not for the whole capture.
            + 'fast' does not use it.
            + Default is None: about 2.8 seconds.
        - `full_page_profile`: str or None, optional
            + How long to wait for the content that loads as the page is
            + scrolled.
            + 'fast' will not wait for it. Images in `loading="lazy"` may
            + then be missing.
            + 'balanced' will wait until the height of the page stops
            + changing, then scroll through it once.
            + 'robust' will scroll through the page until it stops
            + growing. It is the slowest.
            + Default is None: 'fast' for pages given as HTML or as a
            + file, 'balanced' for URLs.
        - `full_page_fixed_elements`: str, optional
            + How the elements that stay in place while the page scrolls,
            + such as a fixed header, will appear in the image.
            + 'auto': each one will appear once, at the top or at the
            + bottom of the image, depending on where it is fixed in the
            + window.
            + 'first': they will appear once, as they are when the page
            + is opened.
            + 'last': they will appear once, as they are when the page is
            + scrolled to the end.
            + 'hide': they will not appear.
            + 'preserve': they will be left as the browser shows them, and
            + can appear several times in the image.
            + Sticky elements will stay in their place in the page, except
            + with 'preserve'.
            + Default is 'auto'.
        - `full_page_max_pixels`: int or None, optional
            + The largest number of pixels of the image. A larger page
            + will raise `CaptureTooLargeError` instead of giving a cut
            + image. None removes the limit, which can use a lot of
            + memory.
            + Default is 100,000,000.

        Returns
        -------
        - list of str
            + A list of the file path(s) of the generated image(s)

        Raises
        ------
        - `FileNotFoundError`
        - `ImportError`
            + With `full_page=True`, if `pyvips` is needed but not
            + installed.
        - `ValueError`
            + If a name given in `save_as` is a path and not a filename,
            + or if a name given in `save_as` ends with .pdf: use the
            + `pdf()` method instead,
            + or if `selector` is used with 'chrome-headless',
            + 'edge-headless' or 'firefox-headless', or is not a valid CSS
            + selector, or if `selector_padding` is negative.
            + If `full_page=True` is used with 'chrome-headless',
            + 'edge-headless' or 'firefox-headless', or with `selector`.
            + With `full_page=True`, if a `full_page_*` option has an
            + invalid value, if a name given in `save_as` does not end
            + with .png, .jpg or .jpeg, or if a size is not made of two
            + positive integers.
        - `ElementNotFoundError`
            + If an element has nothing to capture: no element matches its
            + selector, or it is hidden, empty or outside of the page.
            + The other images will be saved first.
        - `CaptureTooLargeError`
            + If an element is too large for the browser to capture,
            + even with `skip_missing=True`. The other images will be
            + saved first.
            + With `full_page=True`, if a page is larger than
            + `full_page_max_pixels`, or than a JPEG image can be (65,500
            + pixels in width or in height). The other images will be
            + saved first.
        - `Html2ImageError`
            + With `full_page=True`, if `pyvips` could not join the
            + screenshots of a page.

        Warns
        -----
        - `FullPageWarning`
            + With `full_page=True`, if an image was saved but may be
            + wrong in places, for example if the page moved while it was
            + captured, or if it stops before the end of the page.
        """

        # TODO / NOTE : This does not pose any problem for now but setting
        # mutables (here empty lists) as default arguments of a function
        # can cause unwanted behaviours.

        for name in [save_as] if isinstance(save_as, str) else save_as:
            if str(name).lower().endswith('.pdf'):
                raise ValueError(
                    f'"{name}": screenshot() only saves images, '
                    'use pdf() to save PDF files.'
                )

        # An empty string or list counts as no selector.
        selectors = None
        if selector:
            selectors = [selector] if isinstance(selector, str) else selector

        if selectors and not isinstance(
            self.browser, (CDPBrowser, BiDiBrowser)
        ):
            raise ValueError(
                'selector works with the "chrome", "edge" and "firefox" '
                'browsers, not with "chrome-headless", "edge-headless" or '
                '"firefox-headless".'
            )

        if selector_padding < 0:
            raise ValueError(
                'selector_padding should be 0 or more, '
                f'got {selector_padding}.'
            )

        if selectors and full_page:
            raise ValueError(
                'selector and full_page=True cannot be used together: '
                'selector already captures the whole element, even beyond '
                'the window.'
            )

        full_page_options = self._full_page_options(
            full_page, full_page_stability_timeout, full_page_profile,
            full_page_fixed_elements, full_page_max_pixels, save_as, size,
        )

        return self._render(
            html_str=html_str,
            html_file=html_file,
            css_str=css_str,
            css_file=css_file,
            other_file=other_file,
            url=url,
            save_as=save_as,
            size=size,
            selectors=selectors,
            selector_padding=selector_padding,
            skip_missing=skip_missing,
            **full_page_options,
        )

    def pdf(
        self,
        html_str=[],
        html_file=[],
        css_str=[],
        css_file=[],
        other_file=[],
        url=[],
        save_as='document.pdf',
        paper_size='A4',
        landscape=None,
        margin=None,
        background=True,
        scale=1,
    ):
        """ Saves web pages, HTML/CSS strings or files and other files as PDF files.

        The page is printed, as with the "Save as PDF" option of a browser:
        the content is laid out for paper and split into pages, text stays
        selectable and links stay clickable.

        The sources, `save_as` and the returned list work as in the
        `screenshot()` method. There is no `size` parameter: the width of
        the paper replaces the width of the window.

        Parameters
        ----------
        - `html_str`, `html_file`, `css_str`, `css_file`, `other_file`, `url`
            + Same as in the `screenshot()` method.
        - `save_as`: list of str or str
            + Name(s) of the PDF file(s) to create.
            + Default is document.pdf
        - `paper_size`: str or (str, str)
            + Name of a paper size: 'A3', 'A4', 'A5', 'Letter', 'Legal',
              'Tabloid', or 'slide' (16:9, the size of a PowerPoint slide).
              Names are not case-sensitive.
            + Or a (width, height) pair of lengths, e.g. ('15cm', '10cm').
            + If the page sets its own size with a CSS `@page` rule, that
              size is used instead.
            + Default is 'A4'.
        - `landscape`: bool or None
            + True makes the paper wider than tall, False makes it taller
              than wide.
            + None keeps the orientation of `paper_size`: upright for paper
              sizes, sideways for 'slide', as written for a (width, height)
              pair.
            + Default is None.
        - `margin`: str, optional
            + Blank space around the content of each page, written like the
              CSS `margin` property: '1cm' for all sides, '1cm 2cm' for top
              and bottom then left and right, '1cm 2cm 3cm' for top, left
              and right, then bottom, '1cm 2cm 3cm 4cm' for top, right,
              bottom and left.
            + If the page sets its own margins with a CSS `@page` rule, they
              are used instead.
            + Default is 1cm, or 0 for 'slide'.
        - `background`: bool
            + Whether background colors and images are printed.
            + Default is True.
        - `scale`: float
            + Zoom of the content, between 0.1 and 2.
            + Default is 1.

        Lengths are written as in CSS, with a unit: mm, cm, Q, in, pt, pc or
        px (1px is 1/96 of an inch). A length without unit is only accepted
        if it is 0.

        Returns
        -------
        - list of str
            + A list of the file path(s) of the generated PDF(s)

        Raises
        ------
        - `ValueError`
            + If the browser cannot print to PDF: use 'chrome', 'edge' or
              'firefox', not 'chrome-headless', 'edge-headless' or
              'firefox-headless',
            + or if an option has an invalid value.
        """
        if not isinstance(self.browser, (CDPBrowser, BiDiBrowser)):
            raise ValueError(
                'pdf() works with the "chrome", "edge" and "firefox" '
                'browsers, not with "chrome-headless", "edge-headless" or '
                '"firefox-headless".'
            )

        return self._render(
            html_str=html_str,
            html_file=html_file,
            css_str=css_str,
            css_file=css_file,
            other_file=other_file,
            url=url,
            save_as=save_as,
            size=[],
            pdf_options=Html2Image._prepare_pdf_options(
                paper_size, landscape, margin, background, scale
            ),
        )

    def _render(
        self,
        html_str,
        html_file,
        css_str,
        css_file,
        other_file,
        url,
        save_as,
        size,
        selectors=None,
        selector_padding=0,
        skip_missing=False,
        **browser_options,
    ):
        """ Renders different resources, see `screenshot()` and `pdf()`.

        `browser_options` are passed to the `screenshot()` method of the
        browser.
        """

        # paths, missing and too large elements of each page
        page_results = []

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

        page_count = (
            len(html_strings) + len(html_files) + len(other_files) + len(urls)
        )
        images_per_page = len(selectors) if selectors else 1
        save_as_filenames = Html2Image._extend_save_as_param(
            save_as_filenames,
            page_count * images_per_page,
        )
        sizes = self._extend_size_param(sizes, page_count)

        for name in save_as_filenames:
            self._check_filename(name)

        css_style_string = '\n'.join(css_strings) + '\n'

        if css_files:
            # add content from css_files, regardless of whether css_strings was present
            css_style_string += Html2Image._prepare_css_string(css_files)


        for css in css_files:
            if os.path.isfile(css):
                self._load_shared_file(css)
            else:
                raise FileNotFoundError(css)

        # Without a profile, a page given as HTML or as a file will be
        # captured as 'fast', and a URL as 'balanced': only pages loaded
        # from the web usually load content as they are scrolled.
        url_options = browser_options
        if browser_options.get('full_page_profile', '') is None:
            url_options = dict(browser_options, full_page_profile='balanced')
            browser_options = dict(browser_options, full_page_profile='fast')

        for html in html_strings:
            names = [save_as_filenames.pop(0) for _ in range(images_per_page)]
            current_size = sizes.pop(0)

            base_name, _ = os.path.splitext(names[0])

            content = Html2Image._prepare_html_string(
                html, css_style_string, self.add_doctype
            )

            with self._temp_file(base_name + '.html') as html_filename:
                self.load_str(content=content, as_filename=html_filename)
                page_results.append(self._screenshot_page(
                    os.path.join(self.temp_path, html_filename),
                    names, current_size, selectors, selector_padding,
                    browser_options,
                ))

        for screenshot_target in html_files + other_files:

            names = [save_as_filenames.pop(0) for _ in range(images_per_page)]
            current_size = sizes.pop(0)

            if os.path.isfile(screenshot_target):
                filename = os.path.basename(screenshot_target)
                with self._temp_file(filename) as temp_filename:
                    self.load_file(
                        src=screenshot_target, as_filename=temp_filename
                    )
                    page_results.append(self._screenshot_page(
                        os.path.join(self.temp_path, temp_filename),
                        names, current_size, selectors, selector_padding,
                        browser_options,
                    ))
            else:
                raise FileNotFoundError(screenshot_target)

        for target_url in urls:
            names = [save_as_filenames.pop(0) for _ in range(images_per_page)]
            current_size = sizes.pop(0)

            page_results.append(self._screenshot_page(
                target_url, names, current_size, selectors, selector_padding,
                url_options,
            ))

        screenshot_paths, missing, too_large, errors = [], [], [], []
        for paths, page_missing, page_too_large, page_errors in page_results:
            screenshot_paths += paths
            missing += page_missing
            too_large += page_too_large
            errors += page_errors

        if errors and browser_options.get('full_page'):
            max_pixels = browser_options['full_page_max_pixels']
            reasons = {}
            for (_, name), error in zip(too_large, errors):
                if isinstance(error, page_fit.FormatLimitError):
                    reason = (
                        'A JPEG image cannot be wider or higher than '
                        f'{page_fit.JPEG_MAX_SIZE:,} pixels. Save it as a '
                        'PNG image instead.'
                    )
                else:
                    reason = (
                        'The image would have had more than '
                        f'{max_pixels:,} pixels, the limit set by '
                        'full_page_max_pixels. Raise the limit, or set it to '
                        'None to remove it.'
                    )
                reasons.setdefault(reason, []).append(name)
            raise CaptureTooLargeError(
                '\n'.join(
                    f'Too large to be captured: {", ".join(names)}.\n{reason}'
                    for reason, names in reasons.items()
                ),
                paths=screenshot_paths,
                too_large=too_large,
            )

        # An image that is cut or wrong is never acceptable, so a too large
        # element is an error even with `skip_missing`.
        if too_large:
            raise CaptureTooLargeError(
                'Too large to be captured in one go: '
                f'{Html2Image._describe_elements(too_large)}.\n'
                'Chrome and Edge can capture at most '
                f'{chrome_cdp.MAX_CAPTURE_SIZE} pixels in width and in '
                f'height, Firefox at most {firefox_bidi.MAX_CAPTURE_SIZE}. '
                'On a page without <!DOCTYPE html>, Firefox may only be able '
                'to capture an element that fits in the window.',
                paths=screenshot_paths,
                too_large=too_large,
            )

        if missing and not skip_missing:
            raise ElementNotFoundError(
                'Nothing to capture for '
                f'{Html2Image._describe_elements(missing)}.\n'
                'Either no element matched the selector, or the element was '
                'hidden, empty or outside of the page. '
                'Use skip_missing=True to skip missing elements.',
                paths=screenshot_paths,
                missing=missing,
            )

        return screenshot_paths

    def _screenshot_page(
        self, input, names, size, selectors, selector_padding,
        browser_options,
    ):
        """ Saves the page `input` as `names`, see `_render()`.

        With `selectors`, `names` holds one name per selector.

        Returns
        -------
        - tuple of four lists
            + The paths of the saved files, then the (selector, name)
            + pairs of the missing elements and of the elements too large
            + to be captured, then the errors raised for the pages too
            + large to be captured with `full_page`, whose selector is
            + None.
        """
        if not selectors:
            try:
                self.browser.screenshot(
                    input=input,
                    output_path=self.output_path,
                    output_file=names[0],
                    size=size,
                    **browser_options,
                )
            except CaptureTooLargeError as error:
                # As with a too large element, the other pages will be
                # saved before the error is raised.
                return [], [], [(None, names[0])], [error]
            return [os.path.join(self.output_path, names[0])], [], [], []

        elements = list(zip(selectors, names))
        missing, too_large = self.browser.screenshot(
            input=input,
            output_path=self.output_path,
            size=size,
            elements=elements,
            selector_padding=selector_padding,
        )
        paths = [
            os.path.join(self.output_path, name)
            for selector, name in elements
            if (selector, name) not in missing + too_large
        ]
        return paths, missing, too_large, []

    @staticmethod
    def _describe_elements(elements):
        """ Returns a text that lists (selector, name) pairs."""
        return ', '.join(
            f'"{selector}" ({name})' for selector, name in elements
        )

    def __enter__(self):
        self.browser.__enter__()
        return self

    def __exit__(self, *exc):
        self.browser.__exit__(*exc)


if __name__ == '__main__':
    pass

