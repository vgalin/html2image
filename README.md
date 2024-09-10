


<h1 align="center">
  <a href="https://github.com/vgalin/html2image">
    <img src="https://raw.githubusercontent.com/vgalin/html2image/master/readme_assets/html2image_black.png" alt="html2image logo" title="html2image" height="200"/>
  </a>
</h1>


<div align="center">

![PyPI](https://img.shields.io/pypi/v/html2image.svg)
![PyPI](https://img.shields.io/pypi/pyversions/html2image.svg)
![PyPI](https://img.shields.io/github/license/vgalin/html2image.svg)
![GitHub](https://img.shields.io/github/v/release/vgalin/html2image?include_prereleases)
![GitHub](https://img.shields.io/github/languages/code-size/vgalin/html2image)


|[PyPI Package](https://pypi.org/project/html2image/)|[GitHub Repository](https://github.com/vgalin/html2image)|
|-|-|

**A lightweight Python package acting as wrapper around the headless mode of existing web browsers, allowing image generation from HTML/CSS strings, files and URLs.**

</div>
&nbsp;

This package has been tested on Windows, Ubuntu (desktop and server) and MacOS. If you encounter any problems or difficulties while using it, feel free to open an issue on the GitHub page of this project. Feedback is also welcome!

⚠️ Disclaimer: Use this package with trusted content only. Processing untrusted or unsanitized input can lead to malicious code execution. Always ensure content safety.

## Principle


Most web browsers have a Headless Mode, which is a way to run them without displaying any graphical interface. Headless mode is mainly used for automated testing but also comes in handy if you want to take screenshots of web pages that are exact replicas of what you would see on your screen if you were using the browser yourself.

However, for the sake of taking screenshots, headless mode is not very convenient to use. HTML2Image aims to hide the inconveniences of the browsers' headless modes while adding useful features, such as allowing the creation of images from simple strings.

For more information about headless modes :
-   (Chrome) [https://developers.google.com/web/updates/2017/04/headless-chrome](https://developers.google.com/web/updates/2017/04/headless-chrome)
-   (Firefox) [https://developer.mozilla.org/en-US/docs/Mozilla/Firefox/Headless_mode](https://web.archive.org/web/20210604151145/https://developer.mozilla.org/en-US/docs/Mozilla/Firefox/Headless_mode)

## Installation
HTML2Image is published on PyPI and can be installed through pip:

```console
pip install --upgrade html2image
```

In addition to this package, at least one of the following browsers **must** be installed on your machine :
-   Google Chrome (Windows, MacOS)
-   Chromium Browser (Linux)
-   Microsoft Edge

## Usage

### First, import the package and instantiate it
```python
from html2image import Html2Image
hti = Html2Image()
```

Multiple arguments can be passed to the constructor:

-   `browser` :  Browser that will be used, can be set to `'chrome'` (default) or `'edge'`.
-   `browser_executable` : The path or the command that can be used to find the executable of a specific browser.
-   `output_path` : Path to the folder to which taken screenshots will be outputted. Default is the current working directory of your python program.
-   `size` : 2-Tuple representing the size of the screenshots that will be taken. Default value is `(1920, 1080)`.
-   `temp_path` : Path that will be used to put together different resources when screenshotting strings of files. Default value is `%TEMP%/html2image` on Windows, and `/tmp/html2image` on Linux and MacOS.
-   `keep_temp_files` : Pass True to this argument to not automatically remove temporary files created in `temp_path`. Default is False.

Example:
```python
hti = Html2Image(size=(500, 200))
```

You can also change these values later: 
``` python
hti.size = (500, 200)
```

### Then take a screenshot

The `screenshot` method is the basis of this package. Most of the time, you won't need to use anything else. It can take screenshots of various things:
- URLs via the `url` parameter;
- HTML and CSS **files** via the `html_file` and `css_file` parameters;
- HTML and CSS **strings** via the `html_str` and `css_str` parameters;
- and "other" types of files via the `other_file` parameter (try it with .svg files!).

And you can also (optional):
- Change the size of the screenshots using the `size` parameter;
- Save the screenshots as a specific name using the `save_as` parameter.

*N.B.: The `screenshot` method returns a **list** containing the path(s) of the screenshot(s) it took.*

### A few examples

- **URL to image**
```python
hti.screenshot(url='https://www.python.org', save_as='python_org.png')
```

- **HTML & CSS strings to image**
```python
html = """<h1> An interesting title </h1> This page will be red"""
css = "body {background: red;}"

hti.screenshot(html_str=html, css_str=css, save_as='red_page.png')
```

- **HTML & CSS files to image**
```python
hti.screenshot(
    html_file='blue_page.html', css_file='blue_background.css',
    save_as='blue_page.png'
)
```

- **Other files to image**
```python
hti.screenshot(other_file='star.svg')
```

- **Change the screenshots' size**
```python
hti.screenshot(other_file='star.svg', size=(500, 500))
```

---

<details>
<summary> Click to show all the images generated with all the code above </summary>
<img src="readme_assets/sample_url_to_img.png" alt="sample_url_to_img.png"/>
<img src="readme_assets/sample_strings_to_img.png" alt="sample_strings_to_img"/>
<img src="readme_assets/sample_files_to_img.png" alt="sample_files_to_img"/>
<img src="readme_assets/sample_other.png" alt="sample_other_to_img"/>
<img src="readme_assets/sample_other_50_50.png" alt="sample_other_50_50"/>

</details>


---

- **Change the directory to which the screenshots are saved**
```python
hti = Html2Image(output_path='my_screenshot_folder')
```
**OR**
```python
hti.output_path = 'my_screenshot_folder'
```

*N.B. : the output path will be changed for all future screenshots.*

---

#### Use lists in place of any parameters while using the `screenshot` method
- Screenshot multiple objects using only one filename, or one filename per file:
```python
# create three files from one filename
hti.screenshot(html_str=['A', 'B', 'C'], save_as='ABC.png')
# outputs ABC_0.png, ABC_1.png, ABC_2.png

# create three files from from different filenames
hti.screenshot(html_str=['A', 'B', 'C'], save_as=['A.png', 'B.png', 'C.png'])
# outputs A.png, B.png, C.png
```
- Take multiple screenshots with the same size
```python
# take four screenshots with a resolution of 100*50
hti.screenshot(
    html_str=['A', 'B', 'C', 'D'],
    size=(100, 50)
)
```
- Take multiple screenshots with different sizes
```python
# take four screenshots with different resolutions from three given sizes
hti.screenshot(
    html_str=['A', 'B', 'C', 'D'],
    size=[(100, 50), (100, 100), (50, 50)]
)
# respectively 100*50, 100*100, 50*50, 50*50
# if not enough sizes are given, the last size in the list will be repeated

```

- Apply CSS string(s) to multiple HTML string(s)
```python
# screenshot two html strings and apply css strings on both
hti.screenshot(
    html_str=['A', 'B'],
    css_str='body {background: red;}'
)

# screenshot two html strings and apply multiple css strings on both
hti.screenshot(
    html_str=['A', 'B'],
    css_str=['body {background: red;}', 'body {font-size: 50px;}']
)

# screenshot one html string and apply multiple css strings on it
hti.screenshot(
    html_str='A',
    css_str=['body {background: red;}', 'body {font-size: 50px;}']
)
```

---

- **Retrieve the path of the generated file(s)**  
The `screenshot` method returns a list containing the path(s) of the screenshot(s):

```python
paths = hti.screenshot(
    html_str=['A', 'B', 'C'],
    save_as="letters.png",
)

print(paths)
# >>> ['D:\\myFiles\\letters_0.png', 'D:\\myFiles\\letters_1.png', 'D:\\myFiles\\letters_2.png']
```

---

#### Change browser flags
In some cases, you may need to change the *flags* that are used to run the headless mode of a browser.

Flags can be used to:
- Change the default background color of the pages;
- Hide the scrollbar;
- Add delay before taking a screenshot;
- Allow you to use Html2Image when you're root, as you will have to specify the `--no-sandbox` flag;

You can find the full list of Chrome / Chromium flags [here](https://peter.sh/experiments/chromium-command-line-switches/).

There are two ways to specify custom flags:
```python
# At the object instanciation
hti = Html2image(custom_flags=['--my_flag', '--my_other_flag=value'])

# Afterwards
hti.browser.flags = ['--my_flag', '--my_other_flag=value']
```

- **Flags example use-case: adding a delay before taking a screenshot**

With Chrome / Chromium, screenshots are fired directly after there is no more "pending network fetches", but you may sometimes want to add a delay before taking a screenshot, to wait for animations to end for example. 
There is a flag for this purpose, `--virtual-time-budget=VALUE_IN_MILLISECONDS`. You can use it like so:

```python
hti = Html2Image(
    custom_flags=['--virtual-time-budget=10000', '--hide-scrollbars']
)

hti.screenshot(url='http://example.org')
```

- **Default flags**

For ease of use, some flags are set by default. However default flags are not used if you decide to specify `custom_flags` or change the value of `browser.flags`:

```python
# Taking a look at the default flags
>>> hti = Html2Image()
>>> hti.browser.flags
['--default-background-color=000000', '--hide-scrollbars']

# Changing the value of browser.flags gets rid of the default flags.
>>> hti.browser.flags = ['--1', '--2']
>>> hti.browser.flags
['--1', '--2'] 

# Using the custom_flags parameter gets rid of the default flags.
>>> hti = Html2Image(custom_flags=['--a', '--b'])
>>> hti.browser.flags
['--a', '--b']
```

## Using the CLI
HTML2image comes with a Command Line Interface which you can use to generate screenshots from files and URLs on the go.

The CLI is a work in progress and may undergo changes.
You can call it by typing `hti` or `html2image` into a terminal.


| argument | description | example |
| - | - | - |
| -h, --help | Shows the help message | `hti -h` |
| -U, --urls | Screenshots a list of URLs | `hti -U https://www.python.org` |
| -H, --html | Screenshots a list of HTML files | `hti -H file.html` |
| -C, --css | Attaches a CSS files to the HTML ones | `hti -H file.html -C style.css` |
| -O, --other | Screenshots a list of files of type "other" | `hti -O star.svg` |
| -S, --save-as | A list of the screenshot filename(s)  | `hti -O star.svg -S star.png` |
| -s, --size | A list of the screenshot size(s) | `hti -O star.svg -s 50,50`|
| -o, --output_path| Change the output path of the screenshots (default is current working directory) | `hti star.svg -o screenshot_dir` |
| -q, --quiet| Disable all CLI's outputs | `hti --quiet` |
| -v, --verbose| More details, can help debugging | `hti --verbose` |
| --chrome_path| Specify a different chrome path ||
| --custom_flags| Specify custom browser flags | 
| --temp_path| Specify a different temp path (where the files are loaded)||

<br>

### ... now within a Docker container !

You can also test the package and the CLI without having to install everything on your local machine, via a Docker container.

- First `git clone` this repo
- `cd` inside it
- Build the image : `docker build -t html2image .`
- Run and get inside the container : `docker run -it html2image /bin/bash`

Inside that container, the `html2image` package as well as `chromium` are installed.

You can load and execute a python script to use the package, or simply use the CLI.

On top of that, you can also use [volumes](https://docs.docker.com/storage/volumes/) to bind a container directory to your local machine directory, allowing you to retrieve the generated images, or even load some resources (HTML, CSS or Python files).

## Testing

Only basic testing is available at the moment. To run tests, install the requirements (Pillow) and run PyTest at the root of the project:
``` console
pip install -r requirements-test.txt
python -m pytest
```


## FAQ

- Can I automatically take a full page screenshot?  
**Sadly no**, it is not easily possible. Html2Image relies on the headless mode of Chrome/Chromium browsers to take screenshots and there is no way to "ask" for a full page screenshot at the moment. If you know a way (by estimating the page size for example), please open an issue or a discussion!

- Can I add delay before taking a screenshot?   
**Yes** you can, please take a look at the `Change browser flags` section of the readme.

- Can I speed up the screenshot-taking process?  
**Yes**, when you are taking a lot of screenshots, you can achieve better performance using Parallel Processing or Multiprocessing methods. You can find an [example of it here](https://github.com/vgalin/html2image/issues/28#issuecomment-862608053).

- Can I make a cookie modal disappear?  
**Yes and no**. **No**, because there is no options to do it magically and [extensions are not supported in headless Chrome](https://bugs.chromium.org/p/chromium/issues/detail?id=706008#c5) (The [`I don't care about cookies`](https://www.i-dont-care-about-cookies.eu/) extension would have been useful in this case). **Yes**, because you can make any element of a page disappear by retrieving its source code, modifying it as you wish, and finally screenshotting the modified source code.
## TODO List
-   A nice CLI (currently in a WIP state).
-   Support for other browsers, such as Firefox, once their screenshot feature becomes operational.
-   PDF generation?
-   Contributing, issue templates, pull request template, code of conduct.

---

*If you see any typos or notice things that are oddly said, feel free to create an issue or a pull request.*
