from html2image import Html2Image

# This file contains examples of how to use the
# load_str, load_file, screenshot_url and screenshot_loaded_file methods.

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

hti = Html2Image()

# image from an url
hti.screenshot_url('https://www.python.org', 'python_org.png', size=(800, 400))

# change output image size for the next images
hti.size = (500, 200)

# image from html & css string
hti.load_str(my_html_string, as_filename='red_page.html')
hti.load_str(my_css_string, as_filename='red_background.css')

hti.screenshot_loaded_file('red_page.html', 'red.png')

# image from html & css files
hti.load_file('blue_page.html')
hti.load_file('blue_background.css')

hti.screenshot_loaded_file('blue_page.html', 'blue.png')

# hti.output_path += "\\images"
# for i in range (25, 300, 25):
#     hti.size = i, i
#     hti.screenshot('blue_page.html', f'loop_{i}.png')
