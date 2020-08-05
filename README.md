# HTML 2 Image

[![Codacy Badge](https://api.codacy.com/project/badge/Grade/bb31a23498d44ab3bdb173f998d87412)](https://app.codacy.com/manual/vgalin/html2image?utm_source=github.com&utm_medium=referral&utm_content=vgalin/html2image&utm_campaign=Badge_Grade_Dashboard)

[
![PyPI](https://img.shields.io/pypi/v/html2image.svg)
![PyPI](https://img.shields.io/pypi/pyversions/html2image.svg)
![PyPI](https://img.shields.io/github/license/vgalin/html2image.svg)
](https://pypi.org/project/html2image/)

**HTML2Image** ("HTML to Image") is **Python** package that acts as a wrapper around the **headless mode** of existing web browsers to *generate images from URLs and from HTML+CSS strings or files*.

HTML2Image is a **work in progress** and has only be used/tested on Windows for now.

## Principle

Most web browsers have a **Headless Mode**, which is a way to run them without displaying any graphical interface. Headless mode is mainly used for automated testings but also comes in handy in our case, because it can be used to take screenshots of web pages that are exact replicas of what you would see on your screen if you were using the browser yourself.

However, for the sake of taking screenshots, headless mode is not very convenient to use. HTML2Image aims to hide the inconveniences of the browsers' headless modes while adding useful features such as allowing to create an image from as little as a string.

For more informations about headless modes :
-  (Chrome) [https://developers.google.com/web/updates/2017/04/headless-chrome](https://developers.google.com/web/updates/2017/04/headless-chrome)
-  (Firefox) [https://developer.mozilla.org/en-US/docs/Mozilla/Firefox/Headless_mode](https://developer.mozilla.org/en-US/docs/Mozilla/Firefox/Headless_mode)

## Installation
html2image is published on PyPI and can be obtained through pip or your favorite package manager :

```pip install html2image```

## Usage

### Import the library and instantiate it
```python
from html2image import HtmlToImage
htmi = HtmlToImage()
```

Possible arguments for the constructor :
-  `browser` :  Browser that will be used, set by default to `'chrome'` (the only browser supported by HTML2Image at the moment)
-  `chrome_path` and  `firefox_path` : The path or the command that can be used to find the `.exe` of a specific browser. For now, `start chrome` is the default value of `chrome_path`.
-  `output_path` : Path to the folder to which taken screenshots will be outputed. Default is the current working directory of your python program.
-  `size` : 2-Tuple reprensenting the size of the screenshots that will be taken. Default value is `(1920, 1080)`.
-  `temp_path` : Path that will be used by HTML2Image put together the different resources . Default value is the path in the `%TEMP%` user variable on windows (type `echo %TEMP%` in a command prompt to see it).

You can also modify these values afterward by accessing the attribute of the same name : 

``` python
htmi.size = (500, 200)
```

**Nota Bene :** If typing `start chrome` in a command prompt (or only `chrome` if you want to do this via Win+R) does not launch chrome, you will have to change this value by your chrome path, for instance by doing :
```python 
htmi.chrome_path = 'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe'
```

### Image from an URL
The following code takes a screenshot of the [python.org](https://www.python.org/) webpage and save it in the current working directory as `python_org.png` :
```python
htmi.url_to_img(url='https://www.python.org/', output_file='python_org.png')
```

Result (using `size=(800, 550)`): 

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

my_css_string = """\
body {
    background: red;
}
"""

# image from html & css string
htmi.load_str(my_html_string, as_filename='red_page.html')
htmi.load_str(my_css_string, as_filename='red_background.css')

htmi.render('red_page.html', 'red.png')
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
htmi.load_file('blue_page.html')
htmi.load_file('blue_background.css')

htmi.render('blue_page.html', 'blue.png')
```

Result (using `size=(500, 200)`): 

![blue_screenshot](/readme_assets/blue.png)

## TODO List
-  Clean the main directory by moving the examples in their own directory
-  Support for OSX and UNIX systems
-  CLI
-  Suport of other browsers, such as Firefox
-  More extensive doc + comments
-  Check if the lib can find the browsers .EXEs