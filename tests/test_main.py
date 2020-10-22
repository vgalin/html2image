from html2image.main import HtmlToImage
from PIL import Image

OUTPUT_PATH = "tests_output"


def test_screenshot_url():
    hti = HtmlToImage(output_path=OUTPUT_PATH)

    paths = hti.screenshot(url='https://www.python.org', save_as="pyorg.png")
    img = Image.open(paths[0])
    assert (1920, 1080) == img.size  # default size


def test_screenshot_multiple_urls():
    hti = HtmlToImage(output_path=OUTPUT_PATH)
    paths = hti.screenshot(
        url=['https://www.python.org', "https://www.example.org/"],
        save_as="mixed_urls.png",
    )

    for path in paths:
        img = Image.open(path)
        assert (1920, 1080) == img.size  # default size


def test_screenshot_url_custom_size():
    hti = HtmlToImage(output_path=OUTPUT_PATH)

    test_size = (334, 485)

    paths = hti.screenshot(
        url='https://www.python.org',
        save_as="pyorg_custom_size.png",
        size=test_size,
    )

    img = Image.open(paths[0])
    assert test_size == img.size  # default size


def test_screenshot_url_custom_sizes():
    hti = HtmlToImage(output_path=OUTPUT_PATH)

    test_sizes = [
        (100, 100),
        (100, 1000),
        (100, 200),
    ]

    paths = hti.screenshot(
        url=[
            'https://www.python.org',
            'https://www.wikipedia.org/',
            'https://www.example.org/',
        ],
        save_as="mixed_urls_custom_sizes.png",
        size=test_sizes,
    )

    for wanted_size, path in zip(test_sizes, paths):
        img = Image.open(path)
        assert wanted_size == img.size  # default size


def test_screenshot_url_sizes_missing_custom_names():
    hti = HtmlToImage(output_path=OUTPUT_PATH)

    test_sizes = [
        (100, 100),
        (100, 1000),
    ]

    paths = hti.screenshot(
        url=[
            'https://www.python.org',
            'https://www.wikipedia.org/',
            'https://www.example.org/',
        ],
        save_as=[
            "python_100_100.png",
            "wikipedia_100_1000.png",
            "example_100_1000.png",
        ],
        size=test_sizes,
    )

    for wanted_size, path in zip(test_sizes, paths):
        img = Image.open(path)
        assert wanted_size == img.size  # default size


def test_screenshot_string():
    hti = HtmlToImage(output_path=OUTPUT_PATH)

    html = "Hello"
    css = "body{background: blue; font-size: 50px;}"

    paths = hti.screenshot(
        html_str=html, css_str=css, save_as="blue_big_hello.png"
    )

    img = Image.open(paths[0])
    pixels = img.load()

    assert (1920, 1080) == img.size  # default size

    # check colors at top left corner
    assert pixels[0, 0] == (0, 0, 255, 255)  # blue + no transparency


def test_screenshot_other_svg():
    hti = HtmlToImage(output_path=OUTPUT_PATH)

    paths = hti.screenshot(
        other_file='./examples/star.svg', save_as="star_svg.png"
    )

    img = Image.open(paths[0])
    pixels = img.load()

    assert (1920, 1080) == img.size  # default size

    # check colors at top left corner
    assert pixels[0, 0] == (0, 0, 0, 0)  # full transparency no color


def test_screensshot_file():
    hti = HtmlToImage(output_path=OUTPUT_PATH)

    paths = hti.screenshot(
        html_file="./examples/blue_page.html",
        css_file="./examples/blue_background.css",
        save_as="from_file.png",
    )

    img = Image.open(paths[0])
    pixels = img.load()

    assert (1920, 1080) == img.size  # default size

    # check colors at top left corner
    assert pixels[0, 0] == (0, 0, 255, 255)  # blue + no transparency
