""" html2image Command Line Interface
"""

import argparse
import os
from html2image import Html2Image


def size_type(string):
    try:
        width, height = map(int, string.split(','))
        if width <= 0 or height <= 0:
            raise argparse.ArgumentTypeError(
                'Width and height must be positive integers.'
            )
        return width, height
    except ValueError:  # incorrect number of values
        raise argparse.ArgumentTypeError(
            f"Size should be W,H (e.g., 1920,1080), instead got '{string}'"
        )
    except Exception as e:  # unexpected errors
        raise argparse.ArgumentTypeError(f"Invalid size format '{string}': {e}")


def main():
    parser = argparse.ArgumentParser(
        description='Generate images from HTML/CSS or URLs using the html2image library.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # Html2Image instantiation arguments
    group_hti_init = parser.add_argument_group('Html2Image Instance Configuration')
    group_hti_init.add_argument(
        '--output-path', '-o',
        default=os.getcwd(),
        help='Directory to save screenshots.'
    )

    # TODO : this list is duplicated from browser_map in html2image.py
    browser_choices = [
        'chrome', 'chromium', 'google-chrome', 'google-chrome-stable',
        'googlechrome', 'edge', 'chrome-cdp', 'chromium-cdp'
    ]
    group_hti_init.add_argument(
        '--browser',
        default='chrome',
        choices=browser_choices,
        help='Browser to use for screenshots.'
    )
    group_hti_init.add_argument(
        '--browser-executable',
        default=None,
        help='Path to the browser executable. Auto-detected if not provided.'
    )
    group_hti_init.add_argument(
        '--cdp-port',
        type=int,
        default=None,
        help='CDP port for CDP-enabled browsers (e.g., chrome-cdp). Default is library-dependent.'
    )
    group_hti_init.add_argument(
        '--temp-path',
        default=None,
        help="Directory for temporary files. Defaults to system temp directory within an 'html2image' subfolder."
    )
    group_hti_init.add_argument(
        '--keep-temp-files',
        action='store_true',
        help='Do not delete temporary files after screenshot generation.'
    )
    group_hti_init.add_argument(
        '--custom-flags',
        nargs='*', 
        default=[],  # If not provided, defaults are used
        help="Custom flags to pass to the browser (e.g., '--no-sandbox' '--disable-gpu'). If provided, these flags will be used."
    )

    # Screenshot sources arguments
    group_sources = parser.add_argument_group('Screenshot Sources (at least one type is required)')
    group_sources.add_argument(
        '--url', '-U',
        nargs='*', default=[],
        metavar='URL',
        help='URL(s) to screenshot.'
    )
    group_sources.add_argument(
        '--html-file',
        nargs='*', default=[],
        metavar='FILE',
        help='HTML file(s) to screenshot.'
    )
    group_sources.add_argument(
        '--html-string',
        nargs='*', default=[],
        metavar='STRING',
        help='HTML string(s) to screenshot.'
    )
    group_sources.add_argument(
        '--css-file',
        nargs='*', default=[],
        metavar='FILE',
        help='CSS file(s) to load. Used by HTML files or applied with HTML strings.'
    )
    group_sources.add_argument(
        '--css-string',
        nargs='*', default=[],
        metavar='STRING',
        help='CSS string(s) to apply. Combined and used with HTML strings.'
    )
    group_sources.add_argument(
        '--other-file', '-O',
        nargs='*', default=[],
        metavar='FILE',
        help='Other file(s) to screenshot (e.g., SVG).'
    )

    # Screenshot output control arguments
    group_output_ctrl = parser.add_argument_group('Screenshot Output Options')
    group_output_ctrl.add_argument(
        '--save-as', '-S',
        nargs='*', default=None,  # html2image handles default naming if only one source
        metavar='FILENAME',
        help='Filename(s) for the output images. If not provided or fewer names than items, names are auto-generated.'
    )
    group_output_ctrl.add_argument(
        '--size', '-s',
        nargs='*', default=[],
        type=size_type,
        metavar='W,H',
        help="Size(s) for screenshots as W,H. If one W,H pair is given, it applies to all. If multiple, they apply to corresponding screenshots; if fewer pairs than items, the last is repeated. If omitted, (1920,1080) is used."
    )

    # General arguments
    group_general = parser.add_argument_group('General Options')
    group_general.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Suppress output from browsers (sets disable_logging=True).'
    )
    group_general.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output, including browser commands if supported by the browser handler.'
    )

    args = parser.parse_args()

    # Prepare Html2Image()
    hti_kwargs = {
        'output_path': args.output_path,
        'browser': args.browser,
        'browser_executable': args.browser_executable,
        'custom_flags': [cf.replace("'", '') for cf in args.custom_flags],
        'disable_logging': args.quiet,
        'temp_path': args.temp_path,
        'keep_temp_files': args.keep_temp_files,
    }

    # Only pass cdp_port if a CDP browser is likely selected and port is given
    if args.cdp_port and 'cdp' in args.browser.lower():
        hti_kwargs['browser_cdp_port'] = args.cdp_port
    elif args.cdp_port:
        print(
            f"Warning: --cdp-port ({args.cdp_port}) was specified, but the selected browser ('{args.browser}') might not be a CDP browser."
        )

    try:
        # Filter out None values so defaults are used for those specific kwargs
        # keep_temp_files and disable_logging are bools, always pass them.
        # custom_flags should be passed even if None, so Html2Image can use its defaults or an empty list.
        active_hti_kwargs = {
            k: v for k, v in hti_kwargs.items()
            if v is not None or k in ['keep_temp_files', 'disable_logging', 'custom_flags']
        }
        hti = Html2Image(**active_hti_kwargs)

    except Exception as e:
        print(f'Error: Could not instantiate Html2Image: {e}')
        exit(1)

    if args.verbose:
        # The `print_command` attribute is specific to ChromiumHeadless.
        # CDP browsers print logs internally.
        if hasattr(hti.browser, 'print_command'):
            hti.browser.print_command = True
            print('Verbose mode: Browser commands will be printed for compatible handlers.')
        else:
            print('Verbose mode enabled. Note: Detailed browser command printing depends on the selected browser handler.')

    has_sources = any([
        args.url, args.html_file, args.html_string, args.other_file
    ])

    # Print help message if no sources were passed
    if not has_sources:
        print('Error: No screenshot sources (URL, HTML file/string, other file) provided.')
        parser.print_usage()
        exit(1)

    # Perform screenshot
    screenshot_kwargs = {
        'url': args.url,
        'html_file': args.html_file,
        'html_str': args.html_string,
        'css_file': args.css_file,
        'css_str': args.css_string,
        'other_file': args.other_file,
        'size': args.size,  # Pass the list of sizes directly from the --size CLI arg
    }

    if args.save_as is not None:
        screenshot_kwargs['save_as'] = args.save_as

    try:
        if args.verbose:
            print('--- Html2Image Instance Configuration ---')
            for k, v in active_hti_kwargs.items():
                print(f'  {k}: {v}')
            print('--- Screenshot Call Arguments ---')
            for k, v in screenshot_kwargs.items():
                if v or k == 'size':  # print if list not empty, or always for size
                    print(f'  {k}: {v}')

        paths = hti.screenshot(**screenshot_kwargs)

        if not args.quiet:
            print(f'Successfully created {len(paths)} image(s):')
            for path in paths:
                print(f'  {path}')

    except FileNotFoundError as e:
        print(f'Error: A required file was not found: {e}')
        exit(1)

    except ValueError as e:  # Can be raised by browser screenshot method for bad size etc.
        print(f'Error: Invalid value encountered: {e}')
        exit(1)

    except Exception as e:
        print(f'An unexpected error occurred during screenshotting: {e}')
        if args.verbose:
            import traceback
            traceback.print_exc()
        exit(1)


if __name__ == '__main__':
    main()
