# HTML 2 Image
[
![PyPI](https://img.shields.io/pypi/v/html2image.svg)
![PyPI](https://img.shields.io/pypi/pyversions/html2image.svg)
![PyPI](https://img.shields.io/github/license/vgalin/html2image.svg)
](https://pypi.org/project/html2image/)
[
![GitHub](https://img.shields.io/github/v/release/vgalin/html2image?include_prereleases)
![GitHub](https://img.shields.io/github/languages/code-size/vgalin/html2image)
](https://github.com/vgalin/html2image)

**HTML2Image** (HTML to Image) is a lightweight **Python** package that acts as a wrapper around the **headless mode** of existing web browsers to *generate images from URLs and from HTML+CSS strings or files*.

HTML2Image has been tested on Windows, Ubuntu (desktop and server) and MacOS. It is currently in a **work in progress** stage, if you encounter any issues while using it, feel free to open an issue on the GitHub page of this project.


## Principle

Most web browsers have a **Headless Mode**, which is a way to run them without displaying any graphical interface. Headless mode is mainly used for automated testings but also comes in handy if you want to take screenshots of web pages that are exact replicas of what you would see on your screen if you were using the browser yourself.

However, for the sake of taking screenshots, headless mode is not very convenient to use. HTML2Image aims to hide the inconveniences of the browsers' headless modes while adding useful features such as allowing to create an image from as little as a string.

For more information about headless modes :
-   (Chrome) [https://developers.google.com/web/updates/2017/04/headless-chrome](https://developers.google.com/web/updates/2017/04/headless-chrome)
-   (Firefox) [https://developer.mozilla.org/en-US/docs/Mozilla/Firefox/Headless_mode](https://developer.mozilla.org/en-US/docs/Mozilla/Firefox/Headless_mode)

## Installation
html2image is published on PyPI and can be installed through pip:


```
pip install --upgrade html2image
```

In addition to this package, at least one of the following browsers but be installed on your machine :
-   Google Chrome (Windows, MacOS)
-   Chromium (Linux)

## Usage

### Import the library and instantiate it
```python
from html2image import HtmlToImage
hti = HtmlToImage()
```

<details>
<summary> Possible arguments for the constructor (click to expand):</summary>

-   `browser` :  Browser that will be used, set by default to `'chrome'` (the only browser supported by HTML2Image at the moment)
-   `chrome_path` and  `firefox_path` : The path or the command that can be used to find the executable of a specific browser.
-   `output_path` : Path to the folder to which taken screenshots will be outputed. Default is the current working directory of your python program.
-   `size` : 2-Tuple reprensenting the size of the screenshots that will be taken. Default value is `(1920, 1080)`.
-   `temp_path` : Path that will be used by html2image to put together different resources *loaded* with the `load_str` and `load_file` methods. Default value is `%TEMP%/html2image` on Windows, and `/tmp/html2image` on Linux and MacOS.

You can also change these values later: 

``` python
hti.size = (500, 200)
```
</details>
<br>

### Image from an URL
The following code takes a screenshot (with a size of 800 * 400 ) of the [python.org](https://www.python.org/) webpage and save it in the current working directory as `python_org.png` :
```python
hti.size = (800, 400)
hti.screenshot_url('https://www.python.org', 'python_org.png')

# One line alternative :
hti.screenshot_url('https://www.python.org', 'python_org.png', size=(800, 400))

# Please note that you don't necessarily have to specify a size.
```

Result : 

![python_org_screenshot](/readme_assets/python_org.png)

### Image from HTML and CSS strings

The following code generates an image from two given strings, an HTML one and a CSS one.  

```python 
...

# minimal html : quite unconventional but browsers can read it anyway
my_html_string = """\
<link rel="stylesheet" href="red_background.css">
<h1> An interesting title </h1>
This page will be red
"""

my_css_string = "body { background: red; }"

# image from html & css string
hti.load_str(my_html_string, as_filename='red_page.html')
hti.load_str(my_css_string, as_filename='red_background.css')

hti.screenshot('red_page.html', 'red.png', size=(500, 200))
```

Result: 

![red_screenshot](/readme_assets/red.png)

### Image from HTML and CSS files

``` css
/* blue_background.css */
body {
    background: blue;
}
```

``` html
<!-- blue_page.html -->
<!doctype html>
<html>
<head>
    <link rel="stylesheet" href="blue_background.css">
</head>

<body>
    <h1> An interesting title </h1>
    This page will be blue
</body>
</html>
```

``` python
...

# image from html & css files
hti.load_file('blue_page.html')
hti.load_file('blue_background.css')

hti.screenshot('blue_page.html', 'blue.png', size=(500, 200))
```

Result: 

![blue_screenshot](/readme_assets/blue.png)

## Using the CLI
html2image comes with a CLI which you can use to generate screenshots from files and urls on the go.

The CLI is a work in progress and may be subject to changes.
You can call it by typing `hti` or `html2image` into a terminal.

Let the CLI handle your inputs:
```
hti https://www.python.org style.css index.html example.svg
```

Or use arguments:

| argument | description | example |
| - | - | - |
| -h, --help | Show help message | `hti -h` |
| -u, --urls | Screenshot a list of URLs | `hti -u https://www.python.org` |
| -f, --files| Screenshot a list of files| `hti -f star.svg test.html`|
| -n, --name | Name the outputted screenshots | `hti star.svg -n red_star` |
| -o, --output_path| Change the output path of the screenshots (default is current working directory) | `hti star.svg -o screenshot_dir` |
| -q, --quiet| Disable all CLI's outputs | `hti --quiet` |
| -v, --verbose| More details, can help debugging | `hti --verbose` |
| --chrome_path| Specify a different chrome path ||
| --temp_path| Specify a different temp path (where the files are loaded)||

<br>

## Note about the way html2image loads files
To better understand how to use html2image, it is important for you to know what it does with your strings and files.

As you may have noticed, html2image requires you to "load" files and strings before taking a screenshot.

Behing the scenes, everything you load is sent to `temp_path`, which is set by default to `%TEMP%\html2image` on Windows, and `/tmp/html2image` on Linux and MacOS.

This directory is used to put together all the resources that are needed to display a web page correctly, like `css`, `js`, and obviously `html` files. In other words : **everything that you load goes, by default, into the same directory**.

When using `load_str` or `load_file`, you have the possiblity to load things under a specific name using the `as_filename` parameter, this is the name that your loaded files and strings will take when they are placed into this directory.
This name is important:
-   For the HTML files, you have to pass this name as an argument to the `screenshot` method.
-   For other files, you have to refer to this name into the HTML file that you are screenshotting.  
    Example: You load a some CSS with `as_filename='my_style.css'`. To take a screenshot with this CSS applied to your HTML, your HTML must contain the line `<link rel="stylesheet" href="my_style.css">`.

## Testing

Only basic testing is available at the moment. To run tests, run PyTest at the root of the project:
```
python -m pytest
```

## TODO List
-   A nice CLI (Currently in a WIP state)
    - A better way to name the CLI's outputed files ?
-   Support of other browsers, such as Firefox
-   More extensive doc + comments
-   PDF generation?
-   Testing on push/PR with GitHub Actions
