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

htmi = HtmlToImage()

# change output image size for the next images (default size was 1920 * 1080)
htmi.size = (800, 550)

# image from an url
htmi.url_to_img(url='https://www.python.org/', output_file='python_org.png')

# image from html & css string
htmi.load_str(my_html_string, as_filename='red_page.html')
htmi.load_str(my_css_string, as_filename='red_background.css')

htmi.render('red_page.html', 'red.png')

# image from html & css files
htmi.load_file('blue_page.html')
htmi.load_file('blue_background.css')

htmi.render('blue_page.html', 'blue.png')




# htmi.output_path += "\\images"
# for i in range (25, 300, 25):
#     htmi.size = i, i
#     htmi.render('blue_page.html', f'loop_{i}.png')