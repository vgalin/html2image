from html2image.main import HtmlToImage

from PIL import Image
import os

OUTPUT_PATH = "tests_output"

SIZE_LIST = (
    (1920, 1080),
    (1280, 720),
    (800, 400),
)


def test_screenshot_file():
    pass


def test_screenshot_string():
    hti = HtmlToImage(output_path=OUTPUT_PATH)

    for size in SIZE_LIST:
        img_name = f'fromstr_{size[0]}_{size[1]}.png'
        img_relative_path = os.path.join(OUTPUT_PATH, img_name)

        html_string = """\
            <link rel="stylesheet" href="background.css">
            <h1> An interesting title </h1>
            Some interesting text
        """

        css_string = (
            "body { background: linear-gradient(90deg, #00f 50%, #0f0 50%);}"
        )

        hti.load_str(html_string, as_filename='page.html')
        hti.load_str(css_string, as_filename='background.css')
        hti.screenshot('page.html', img_name, size=size)

        img = Image.open(img_relative_path)
        pixels = img.load()

        assert size == img.size

        # check colors at top corners
        assert pixels[0, 0] == (0, 0, 255, 255)
        assert pixels[size[1], 0] == (0, 255, 0, 255)


def test_screenshot_url():
    hti = HtmlToImage(output_path=OUTPUT_PATH)

    for size in SIZE_LIST:
        img_name = f'pyorg_{size[0]}_{size[1]}.png'
        img_relative_path = os.path.join(OUTPUT_PATH, img_name)

        hti.screenshot_url(
            'https://www.python.org', img_name, size=size
        )

        img = Image.open(img_relative_path)

        assert size == img.size
