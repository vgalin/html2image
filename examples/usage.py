from html2image import HtmlToImage

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

hti = HtmlToImage()

# change output image size for the next images (default size was 1920 * 1080)
hti.size = (800, 550)

# image from an url
hti.screenshot(url='https://www.python.org/', output_file='python_org.png')

# image from html & css string
hti.load_str(my_html_string, as_filename='red_page.html')
hti.load_str(my_css_string, as_filename='red_background.css')

hti.render(file='red_page.html', output_file='red.png')

# image from html & css files
hti.load_file('blue_page.html')
hti.load_file('blue_background.css')

hti.render(file='blue_page.html', output_file='blue.png')




# hti.output_path += "\\images"
# for i in range (25, 300, 25):
#     hti.size = i, i
#     hti.render('blue_page.html', f'loop_{i}.png')