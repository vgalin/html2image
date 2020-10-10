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

        # if file is not a css or js file, screen it
        if not file.endswith('.css') or not file.endswith('.js'):
            htmi.screenshot(file, f'{output_name}{output_index}.png')
            logging.info(f'Screened file {file} as {file}.png')

    def handle_url(url):
        htmi.screenshot_url(url, f'{output_name}{output_index}.png')
        logging.info(f'Screened url {url} as {output_name}{output_index}.png')

    def sort_args(args):
        ''' Sort an argument list, placing .css and .js files first.

            It is better to sort (non url) arguments before calling
            handle_file, as we want styles (css) and scripts (js) to be
            loaded before, for instance, html files.
        '''

        screenshottables = []
        others = []

        for arg in args:
            if arg.endswith('.css') or arg.endswith('.js'):
                others.append(arg)
            else:
                screenshottables.append(arg)

        return others + screenshottables

    parser = argparse.ArgumentParser()

    parser.add_argument('inputs', nargs='*')
    parser.add_argument('-u', '--urls', nargs='*', required=False, default=[])
    parser.add_argument('-f', '--files', nargs='*', required=False, default=[])

    parser.add_argument('-s', '--size', nargs=2, required=False)
    parser.add_argument('-n', '--name', type=int, required=False)  # sshot.png
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

    if args.name:
        output_name = args.name
    else:
        output_name = 'screenshot'

    output_index = 0

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

    args.inputs = sort_args(args.inputs)
    args.files = sort_args(args.files)

    # handling items that can be urls or files
    for item in args.inputs:

        if os.path.isfile(item):  # screen file
            handle_file(item)
            output_index += 1

        elif item.startswith('http'):  # screen url
            handle_url(item)
            output_index += 1

        else:
            logging.error(f'Invalid item \t{item}')
            logging.error('Maybe the protocol (http, https) is missing ?')

    for url in args.urls:
        if not url.startswith('http'):
            logging.info(f'Adding missing protocol to {url}')
            url = 'https://' + url

        handle_url(url)
        output_index += 1

    for file in args.files:
        if not os.path.isfile(file):
            logging.error(f'Cannot find file {file}')
            continue

        handle_file(file)
        output_index += 1


if __name__ == "__main__":
    cli_entry()
