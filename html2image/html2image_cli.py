""" html2image Command Line Interface
"""

import argparse
import os
import logging

from html2image import HtmlToImage


def cli_entry():

    print('CLI for html2image is not implemented yet.')

    parser = argparse.ArgumentParser()

    parser.add_argument('inputs', nargs='*')  # file.a, file.b, file.c
    parser.add_argument('-u', '--urls', nargs='*', required=False)
    parser.add_argument('-f', '--files', nargs='*', required=False)

    parser.add_argument('-s', '--size', nargs=2, required=False)
    parser.add_argument('-n', '--name', required=False)  # screenshot.png
    parser.add_argument('-o', '--output_path', required=False)

    parser.add_argument('-q', '--quiet', required=False, action="store_true")
    parser.add_argument('-v', '--verbose', required=False, action="store_true")

    parser.add_argument('--browser', required=False)
    parser.add_argument('--chrome_path', required=False)
    parser.add_argument('--firefox_path', required=False)
    parser.add_argument('--temp_path', required=False)

    args = parser.parse_args()

    if args.quiet:
        logging.basicConfig(level=logging.CRITICAL)
    elif args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
        # logging.basicConfig(filename='example.log',level=logging.DEBUG)

    logging.debug(f'{args = }')

    try:
        htmi = HtmlToImage()
    except Exception as e:
        logging.critical('Could not instanciate html2image.')
        logging.exception(e)
        exit()
    else:
        logging.debug('html2Image has been correctly instanciated')

    if args.size:
        htmi.size = tuple(args.size)

    if args.output_path:
        htmi.output_path = args.output_path

    for item in args.inputs:

        if item.startswith('http'):  # screen url
            # todo output.name
            output_name = 'screenshot.png'

            htmi.screenshot_url(item, output_name)
            logging.info(f'screened url \t{item}')

        elif os.path.isfile(item):  # screen file
            htmi.load_file(item)

            if not item.endswith('.css'):
                # if item is not a css file, screen it
                htmi.screenshot(item, f'{item}.png')
                logging.info(f'screened file \t{item}')

        else:
            logging.error(f'invalid item \t{item}')

    # if len(args.files) == 0:
    #     args.files = None

    # if args.url is not None and args.files is not None:
    #     print('todo')


# todo delete
if __name__ == '__main__':
    cli_entry()
