import os
import codecs
from shutil import copyfile

# default_chrome_path = 'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe'
default_chrome_path = 'start chrome'
default_firefox_path = 'start firefox'

class HtmlToImage():
    
    # todo : check if output path exists on init or on attribute change

    def __init__(
        self,
        browser='chrome',
        chrome_path=default_chrome_path,
        firefox_path=default_firefox_path,
        output_path=os.getcwd(),
        size=(1920, 1080),
        temp_path=os.path.join(os.environ['TEMP'], 'html2image'),
    ):
        """
        """
        self.browser = browser
        self.chrome_path = chrome_path
        self.firefox_path = firefox_path
        self.output_path = output_path
        self.size = size
        self.temp_path = temp_path

        if self.browser == "chrome":
            self._render = self._chrome_render
        elif self.browser == "firefox":
            self._render = self._firefox_render
        else:
            raise NotImplementedError
    
    @property
    def size(self):
        return tuple(int(i) for i in self._size.split(','))
    
    @size.setter
    def size(self, value):
        self._size = f'{value[0]},{value[1]}'

    def render(self, html_file, image_name):
        """

        """
        html_file = os.path.join(self.temp_path, html_file)
        self._render(output_file=image_name, input=html_file)

    def _chrome_render(self, output_file='render.png', input=''):
        """

        """

        # multiline str representing the command used to launch chrome in
        # headless mode and take a screenshot
        command = (
            f'"{self.chrome_path}" '
            f'--headless '
            f'--screenshot={os.path.join(self.output_path, output_file)} '
            f'--window-size={self._size} '
            f'--default-background-color=0 '
            f'{input}'
        )
        # print(command)
        os.system(command)

    def _firefox_render(self, output_file='render.png', input=''):
        """
        
        """
        raise NotImplementedError

    def url_to_img(self, url, output_file='render.png'):
        self._render(input=url, output_file=output_file)

    def load_str(self, css_content, as_filename):
        with open(os.path.join(self.temp_path, as_filename), 'w') as f:
            f.writelines(css_content)

    def load_file(self, src, as_filename=None):
        if as_filename is None:
            as_filename = os.path.basename(src)

        dest = os.path.join(self.temp_path, as_filename)
        copyfile(src, dest)


if __name__ == '__main__':
    pass