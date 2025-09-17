from html2image import Html2Image
from PIL import Image, ImageChops

import pytest
import os

OUTPUT_PATH = "tests_output"
os.makedirs(OUTPUT_PATH, exist_ok=True)

TEST_BROWSERS = ["edGe", "cHrOme"]


def test_bad_browser():
    with pytest.raises(ValueError):
        Html2Image(browser="watergoupil")


@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_good_browser(browser):
    Html2Image(browser=browser)


@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_url(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    paths = hti.screenshot(url="https://www.python.org", save_as="pyorg.png")
    img = Image.open(paths[0])
    assert (1920, 1080) == img.size  # default size


@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_multiple_urls(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)
    paths = hti.screenshot(
        url=["https://www.python.org", "https://www.example.org/"],
        save_as="mixed_urls.png",
    )

    for path in paths:
        img = Image.open(path)
        assert (1920, 1080) == img.size  # default size


@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_url_custom_size(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    test_size = (334, 485)

    paths = hti.screenshot(
        url="https://www.python.org",
        save_as="pyorg_custom_size.png",
        size=test_size,
    )

    img = Image.open(paths[0])
    assert test_size == img.size  # default size


@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_url_custom_sizes(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    test_sizes = [
        (100, 100),
        (100, 1000),
        (100, 200),
    ]

    paths = hti.screenshot(
        url=[
            "https://www.python.org",
            "https://www.wikipedia.org/",
            "https://www.example.org/",
        ],
        save_as="mixed_urls_custom_sizes.png",
        size=test_sizes,
    )

    for wanted_size, path in zip(test_sizes, paths):
        img = Image.open(path)
        assert wanted_size == img.size


@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_url_sizes_missing_custom_names(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    test_sizes = [
        (100, 100),
        (100, 1000),
    ]

    paths = hti.screenshot(
        url=[
            "https://www.python.org",
            "https://www.wikipedia.org/",
            "https://www.example.org/",
        ],
        save_as=[
            "python_100_100.png",
            "wikipedia_100_1000.png",
            "example_100_1000.png",
        ],
        size=test_sizes,
    )
    effective_wanted_sizes = test_sizes + [test_sizes[-1]]
    for wanted_size, path in zip(effective_wanted_sizes, paths):
        img = Image.open(path)
        assert wanted_size == img.size


@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_string(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    html = "Hello"
    css = "body{background: blue; font-size: 50px;}"

    paths = hti.screenshot(html_str=html, css_str=css, save_as="blue_big_hello.png")

    img = Image.open(paths[0])
    pixels = img.load()

    assert (1920, 1080) == img.size  # default size

    # check colors at top left corner
    assert pixels[0, 0][:3] == (0, 0, 255)


@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_string_different_sizes(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    test_sizes = [
        (100, 100),
        (100, 1000),
        (100, 200),
    ]

    html = "Hello"

    paths = hti.screenshot(
        html_str=[html] * 3, save_as="from_string_custom_size.png", size=test_sizes
    )

    for wanted_size, path in zip(test_sizes, paths):
        img = Image.open(path)
        assert wanted_size == img.size


@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_other_svg(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    paths = hti.screenshot(other_file="./examples/star.svg", save_as="star_svg.png")

    img = Image.open(paths[0])
    pixels = img.load()

    assert (1920, 1080) == img.size  # default size

    # check colors at top left corner (assuming transparent background for the SVG)
    # for transparent PNG, the alpha channel will be 0
    assert pixels[0, 0][3] == 0  # check alpha channel for full transparency


@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_file(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    paths = hti.screenshot(
        html_file="./examples/blue_page.html",
        css_file="./examples/blue_background.css",  # this CSS file is linked in blue_page.html
        save_as="from_file.png",
    )

    img = Image.open(paths[0])
    pixels = img.load()

    assert (1920, 1080) == img.size  # default size

    # check colors at top left corner
    assert pixels[0, 0][:3] == (0, 0, 255)  # blue + no transparency


@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_file_different_sizes(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    test_sizes = [
        (100, 100),
        (100, 1000),
        (100, 200),
    ]

    paths = hti.screenshot(
        html_file=["./examples/blue_page.html"] * 3,
        save_as="from_file_custom_size.png",
        size=test_sizes,
    )

    for wanted_size, path in zip(test_sizes, paths):
        img = Image.open(path)
        assert wanted_size == img.size


@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_html_str_with_css_file_only(browser):
    """Test html_str styled by a css_file only."""
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)
    html_content = "<h1>Background should be blue from file</h1>"
    css_file_path = "./examples/blue_background.css"

    paths = hti.screenshot(
        html_str=html_content,
        css_file=css_file_path,
        save_as="html_str_blue_bg_from_file.png",
    )

    img = Image.open(paths[0])
    pixels = img.load()
    assert (1920, 1080) == img.size

    # Check top-left corner for blue background
    assert pixels[0, 0][:3] == (0, 0, 255)  # blue


@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_html_str_with_css_str_and_css_file(browser):
    """Test html_str styled by both css_str (for a green block) and css_file (for blue body background)."""
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    # this CSS describes a green block, positioned absolutely,
    # using !important to ensure these styles apply
    css_string_content = """
    #green-block {
        background-color: rgb(0, 255, 0) !important; /* Green background */
        width: 150px !important;
        height: 100px !important;
        position: absolute !important;
        top: 75px !important;
        left: 75px !important;
    }
    """

    css_file_path = "./examples/blue_background.css"

    # div that will be styled by css_string_content
    html_content = '<div id="green-block"></div>'

    paths = hti.screenshot(
        html_str=html_content,
        css_str=css_string_content,  # Styles #green-block
        css_file=css_file_path,  # Styles body background
        save_as="html_str_green_block_blue_bg.png",
        size=(500, 400),
    )

    img = Image.open(paths[0])
    pixels = img.load()
    assert (500, 400) == img.size

    # check body background color (blue)
    assert pixels[10, 10][:3] == (0, 0, 255)  # blue

    # check #green-block color (green from css_string_content)
    assert pixels[150, 125][:3] == (0, 255, 0)  # green


@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_screenshot_html_str_with_multiple_css_files(browser):
    """Test html_str styled by multiple css_files using distinct background colors."""
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    # this CSS describes a red block, positioned absolutely,
    # using !important to ensure these styles apply
    temp_css_content = """
    #red-block {
        background-color: rgb(255, 0, 0) !important; /* red background */
        width: 200px !important;
        height: 150px !important;
        position: absolute !important; /* for predictable positioning */
        top: 50px !important;
        left: 50px !important;
    }
    """
    temp_css_filename = os.path.join(OUTPUT_PATH, "_temp_red_block.css")
    with open(temp_css_filename, "w") as f:
        f.write(temp_css_content)

    # the div that will be styled by _temp_red_block.css
    html_content = '<div id="red-block"></div>'

    css_file_paths = [
        "./examples/blue_background.css",  # sets body { background: blue; }
        temp_css_filename,  # styles #red-block
    ]

    paths = hti.screenshot(
        html_str=html_content,
        css_file=css_file_paths,
        save_as="html_str_multi_css_blocks.png",
        size=(400, 300),
    )

    # clean up temporary CSS file
    if os.path.exists(temp_css_filename):
        os.remove(temp_css_filename)

    img = Image.open(paths[0])
    pixels = img.load()
    assert (400, 300) == img.size

    # check body background color (blue)
    assert pixels[10, 10][:3] == (0, 0, 255)  # blue

    # check #green-block color (red from _temp_red_block.css)
    assert pixels[150, 125][:3] == (255, 0, 0)  # red


@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_extend_size_param(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    assert hti._extend_size_param([(50, 50)], 1) == [(50, 50)]

    assert hti._extend_size_param([(50, 50)], 3) == [(50, 50), (50, 50), (50, 50)]

    assert hti._extend_size_param([(50, 50), (70, 60), (80, 90)], 5) == [
        (50, 50),
        (70, 60),
        (80, 90),
        (80, 90),
        (80, 90),
    ]

    assert hti._extend_size_param([], 3) == [(1920, 1080), (1920, 1080), (1920, 1080)]


@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_extend_save_as_param(browser):
    hti = Html2Image(browser=browser, output_path=OUTPUT_PATH, disable_logging=True)

    assert hti._extend_save_as_param(["a.png", "b.png"], 2) == ["a.png", "b.png"]

    assert hti._extend_save_as_param(["a.png", "b.png"], 4) == [
        "a.png",
        "b_0.png",
        "b_1.png",
        "b_2.png",
    ]

    assert hti._extend_save_as_param(["a.png", "b.png"], 0) == ["a.png", "b.png"]

    assert hti._extend_save_as_param(["a.png", "b.png", None, 65], 2) == [
        "a.png",
        "b.png",
    ]


@pytest.mark.parametrize("browser", TEST_BROWSERS)
def test_force_device_scale_factor(browser):
    hti = Html2Image(
        browser=browser,
        output_path=OUTPUT_PATH,
        disable_logging=True,
        force_device_scale_factor=2,
    )

    assert hti.force_device_scale_factor == "--force-device-scale-factor=2"
    hti.screenshot(url="https://www.python.org", save_as="pyorg.png")
    img = Image.open(
        hti.screenshot(url="https://www.python.org", save_as="pyorg.png")[0]
    )
    assert (3840, 2160) == img.size  # default size
