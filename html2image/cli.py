""" html2image Command Line Interface
"""

import argparse

from html2image import Html2Image


def main():

    def size_type(string):
        try:
            x, y = map(int, string.split(','))
            return x, y
        except Exception:
            raise argparse.ArgumentTypeError(
                f"size should be int,int, instead got {string}"
            )

    parser = argparse.ArgumentParser()

    parser.add_argument('-U', '--url', nargs='*', required=False, default=[])
    parser.add_argument('-H', '--html', nargs='*', required=False, default=[])
    parser.add_argument('-C', '--css', nargs='*', required=False, default=[])
    parser.add_argument('-O', '--other', nargs='*', required=False, default=[])

    parser.add_argument(
        '-S', '--save-as', nargs='*', required=False, default="screenshot.png"
    )
    parser.add_argument(
        '-s', '--size', nargs='*', required=False, default=[], type=size_type
    )

    parser.add_argument('-o', '--output_path', required=False)

    parser.add_argument('-q', '--quiet', required=False, action="store_true")
    parser.add_argument('-v', '--verbose', required=False, action="store_true")

    # parser.add_argument('--browser', required=False)
    parser.add_argument('--chrome_path', required=False)
    # parser.add_argument('--firefox_path', required=False)
    parser.add_argument('--temp_path', required=False)
    parser.add_argument('--custom_flags', required=False)

    args = parser.parse_args()

    try:
        hti = Html2Image(disable_logging=args.quiet)
    except Exception as e:
        print('Could not instanciate html2image.')
        print(e)
        exit(1)

    if args.verbose:
        print(f'args = {args}')
        hti.browser.print_command = True

    if args.output_path:
        hti.output_path = args.output_path

    if args.chrome_path:
        hti.chrome_path = args.chrome_path

    if args.custom_flags:
        hti.browser.flags = args.custom_flags

    if args.temp_path:
        hti.temp_path = args.temp_path

    paths = hti.screenshot(
        html_file=args.html, css_file=args.css, other_file=args.other,
        url=args.url, save_as=args.save_as, size=args.size
    )

    if not args.quiet:
        print(f'Created {len(paths)} file(s):')
        for path in paths:
            print(f'\t{path}')


if __name__ == "__main__":
    main()
