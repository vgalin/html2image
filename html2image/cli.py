""" html2image Command Line Interface
"""

import argparse
import os
import logging

from main import HtmlToImage


def cli_entry():

    def size_type(string):
        try:
            x, y = map(int, string.split(','))
            return x, y
        except:
            raise argparse.ArgumentTypeError(
                f"size should be int,int, instead got {string}"
            )

    try:
        htmi = HtmlToImage()
    except Exception as e:
        logging.critical('Could not instanciate html2image.')
        logging.exception(e)
        exit(1)

    parser = argparse.ArgumentParser()

    parser.add_argument('inputs', nargs='*')
    parser.add_argument('-U', '--url', nargs='*', required=False, default=[])
    parser.add_argument('-H', '--html', nargs='*', required=False, default=[])
    parser.add_argument('-C', '--css', nargs='*', required=False, default=[])
    parser.add_argument('-O', '--other', nargs='*', required=False, default=[])

    parser.add_argument('-S', '--save-as', nargs='*', required=False, default=[])
    parser.add_argument('-s', '--size', nargs='*', required=False, default=[], type=size_type)

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

    htmi.screenshot(
        html_file=args.html, css_file=args.css, other_file=args.other,
        url=args.url, save_as=args.save_as, size=args.size
    )

if __name__ == "__main__":
    cli_entry()
