""" html2image Command Line Interface
"""

import argparse
import os
import logging

from html2image import HtmlToImage


def cli_entry():

    try:
        htmi = HtmlToImage()
    except Exception as e:
        logging.critical('Could not instanciate html2image.')
        logging.exception(e)
        exit(1)

    def handle_file(file):
        htmi.load_file(file)
        logging.info(f'Loaded file \t{file}')

        # if file is not a css file, screen it
        if not file.endswith('.css'):
            htmi.screenshot(file, f'{file}.png')
            logging.info(f'Screened file \t{file} as {file}.png')

    def handle_url(url):
        # TODO : a changing output_name
        output_name = 'screenshot_url.png'
        htmi.screenshot_url(url, output_name)
        logging.info(f'Screened url \t{url} as {output_name}')

    parser = argparse.ArgumentParser()

    parser.add_argument('inputs', nargs='*')  # file.a, file.b, file.c
    parser.add_argument('-u', '--urls', nargs='*', required=False, default=[])
    parser.add_argument('-f', '--files', nargs='*', required=False, default=[])

    parser.add_argument('-s', '--size', nargs=2, required=False)
    parser.add_argument('-n', '--name', required=False)  # screenshot.png
    parser.add_argument('-o', '--output_path', required=False)

    parser.add_argument('-q', '--quiet', required=False, action="store_true")
    parser.add_argument('-v', '--verbose', required=False, action="store_true")

    parser.add_argument('--browser', required=False)
    parser.add_argument('--chrome_path', required=False)
    # parser.add_argument('--firefox_path', required=False)
    parser.add_argument('--temp_path', required=False)
    # todo: flag 'ask_for_filename' ?

    args = parser.parse_args()

    if args.quiet:
        logging.basicConfig(level=logging.CRITICAL)
    elif args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    logging.debug(f'{args = }')

    if args.size:
        htmi.size = tuple(args.size)

    if args.output_path:
        htmi.output_path = args.output_path

    if args.browser:
        htmi.browser = args.browser

    if args.chrome_path:
        htmi.chrome_path = args.chrome_path

    # if args.firefox_path:
    #     htmi.firefox_path = args.firefox_path

    if args.temp_path:
        htmi.temp_path = args.temp_path

    # handling items that can be urls or files
    for item in args.inputs:

        if os.path.isfile(item):  # screen file
            handle_file(item)

        elif item.startswith('http'):  # screen url
            handle_url(item)

        else:
            logging.error(f'Invalid item \t{item}')
            logging.error('Maybe the protocol (http, https) is missing ?')

    for url in args.urls:
        if not url.startswith('http'):
            logging.info(f'Adding missing protocol to {url}')
            url = 'https://' + url

        handle_url(url)

    for file in args.files:
        if not os.path.isfile(file):
            logging.error(f'Cannot find file {file}')
            continue

        handle_file(file)


if __name__ == "__main__":
    cli_entry()
