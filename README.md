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

HTML2Image is currently in a **work in progress** stage.

## Principle

Most web browsers have a **Headless Mode**, which is a way to run them without displaying any graphical interface. Headless mode is mainly used for automated testings but also comes in handy if you want to take screenshots of web pages that are exact replicas of what you would see on your screen if you were using the browser yourself.

However, for the sake of taking screenshots, headless mode is not very convenient to use. HTML2Image aims to hide the inconveniences of the browsers' headless modes while adding useful features such as allowing to create an image from as little as a string.

For more information about headless modes :
-   (Chrome) [https://developers.google.com/web/updates/2017/04/headless-chrome](https://developers.google.com/web/updates/2017/04/headless-chrome)
-   (Firefox) [https://developer.mozilla.org/en-US/docs/Mozilla/Firefox/Headless_mode](https://developer.mozilla.org/en-US/docs/Mozilla/Firefox/Headless_mode)

## Installation
html2image is published on PyPI and can be obtained through pip or your favorite package manager :

```pip install html2image```

## Usage

### Import the library and instantiate it
```python
from html2image import HtmlToImage
hti = HtmlToImage()
```

Possible arguments for the constructor :
-   `browser` :  Browser that will be used, set by default to `'chrome'` (the only browser supported by HTML2Image at the moment)
-   `chrome_path` and  `firefox_path` : The path or the command that can be used to find the `.exe` of a specific browser. For now, `start chrome` is the default value of `chrome_path`.
-   `output_path` : Path to the folder to which taken screenshots will be outputed. Default is the current working directory of your python program.
-   `size` : 2-Tuple reprensenting the size of the screenshots that will be taken. Default value is `(1920, 1080)`.
-   `temp_path` : Path that will be used by HTML2Image put together the different resources . Default value is the path in the `%TEMP%` user variable on windows (type `echo %TEMP%` in a command prompt to see it).

You can also modify these values afterward by accessing the attribute of the same name : 

``` python
hti.size = (500, 200)
```

### Image from an URL
The following code takes a screenshot (with a size of 800 * 400 ) of the [python.org](https://www.python.org/) webpage and save it in the current working directory as `python_org.png` :
```python
hti.size = (800, 400)
hti.screenshot_url('https://www.python.org', 'python_org.png')

# one line alternative :
hti.screenshot_url('https://www.python.org', 'python_org.png', size=(800, 400))

```

Result : 

![blue_screenshot](/readme_assets/python_org.png)

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

hti.screenshot('red_page.html', 'red.png')
```

Result (using `size=(500, 200)`): 

![blue_screenshot](/readme_assets/red.png)

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

hti.screenshot('blue_page.html', 'blue.png')
```

Result (using `size=(500, 200)`): 

![blue_screenshot](/readme_assets/blue.png)

## TODO List
-   A nice CLI
-   Suport of other browsers, such as Firefox
-   More extensive doc + comments
-   Deep search for the browsers executables?
-   PDF generation?
