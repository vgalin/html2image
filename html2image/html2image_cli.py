""" html2image Command Line Interface
"""

import argparse
import os
import logging

from html2image import HtmlToImage


def cli_entry():

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
    parser.add_argument('--firefox_path', required=False)
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

    try:
        htmi = HtmlToImage()
    except Exception as e:
        logging.critical('Could not instanciate html2image.')
        logging.exception(e)
        exit(1)

    if args.size:
        htmi.size = tuple(args.size)

    if args.output_path:
        htmi.output_path = args.output_path

    # handling items that can be urls or files
    for item in args.inputs:

        if os.path.isfile(item):  # screen file
            htmi.load_file(item)

            # if item is not a css file, screen it
            if not item.endswith('.css'):
                htmi.screenshot(item, f'{item}.png')
                logging.info(f'screened file \t{item} as {item}.png')

        elif item.startswith('http'):  # screen url
            # todo output name
            output_name = 'screenshot.png'

            htmi.screenshot_url(item, output_name)
            logging.info(f'screened url \t{item} as {output_name}')

        else:
            logging.error(f'invalid item \t{item}')

    for url in args.urls:
        if not url.startswith('http'):
            logging.info(f'adding missing protocol to {url}')
            url = 'https://' + url

        # todo output name
        output_name = 'screenshot_url.png'
        htmi.screenshot_url(url, output_name)
        logging.info(f'screened url \t{url} as {output_name}')

    for file in args.files:
        if not os.path.isfile(file):
            logging.error(f'cannot find file {file}')
            continue

        htmi.load_file(file)
        logging.info(f'loaded file \t{file}')

        # if file is not a css file, screen it
        if not file.endswith('.css'):
            htmi.screenshot(file, f'{file}.png')
            logging.info(f'screened file \t{file} as {file}.png')


# todo delete
if __name__ == '__main__':
    cli_entry()
