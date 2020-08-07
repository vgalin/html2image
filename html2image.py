"""
Main file of the html2image package.

html2image ia a package acting as a wrapper around the
headless modeof existing web browsers to generate images
from URLs and from HTML+CSS strings or files.
"""

import os
import shutil


def _find_chrome(user_given_path=None):
    """
    Checks the validity of a given path.
    If no path given, try to find chrome on a Windows or Unix system.
    """

    if user_given_path is not None:
        if os.path.isfile(user_given_path):
            return user_given_path
        else:
            print('Could not find chrome in the given path.')
            exit(1)

    if os.name == 'nt':
        # Windows system
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

    else:
        # Other systems (not Windows)

        # test for the most common directory first
        if os.path.isfile("/usr/bin/chromium-browser"):
            return "/usr/bin/chromium-browser"

        # search for chromium-browser with a python equivalent of the `which` command
        which_result = shutil.which('chromium-browser')
        if os.path.isfile(which_result):
            return which_result

    print('Could not find a Chrome executable on this machine, please specify it yourself.')
    exit(1)


class HtmlToImage():

    # todo : check if output path exists on init or on attribute change

    def __init__(
        self,
        browser='chrome',
        chrome_path=None,
        firefox_path=None,
        output_path=os.getcwd(),
        size=(1920, 1080),
        temp_path=None,
    ):
        """
        """
        self.browser = browser
        self.output_path = output_path
        self.size = size
        self.temp_path = temp_path

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

    def render(self, html_file, image_name):
        """

        """
        html_file = os.path.join(self.temp_path, html_file)
        self._render(output_file=image_name, input_file=html_file)

    def _chrome_render(self, output_file='render.png', input_file=''):
        """

        """

        # multiline str representing the command used to launch chrome in
        # headless mode and take a screenshot
        command = (
            f'"{self.chrome_path}" '
            f'--headless '
            f'--screenshot={os.path.join(self.output_path, output_file)} '
            f'--window-size={self.size[0]},{self.size[1]} '
            f'--default-background-color=0 '
            f'--hide-scrollbars ' # TODO : make it possible to choose to display it or not
            f'{input_file}'
        )
        # print(command)
        os.system(command)

    def _firefox_render(self, output_file='render.png', input_file=''):
        """
        """
        raise NotImplementedError

    def url_to_img(self, url, output_file='render.png'):
        self._render(input_file=url, output_file=output_file)

    def load_str(self, css_content, as_filename):
        with open(os.path.join(self.temp_path, as_filename), 'w') as f:
            f.writelines(css_content)

    def load_file(self, src, as_filename=None):
        if as_filename is None:
            as_filename = os.path.basename(src)

        dest = os.path.join(self.temp_path, as_filename)
        shutil.copyfile(src, dest)


if __name__ == '__main__':
    pass
