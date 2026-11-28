"""Start Chrome, Edge and Firefox once each, before the tests.

Each browser is found the same way as in the tests. On a new machine, the
first start of a browser can take more than a minute, and later starts
about half a second. Starting each browser here keeps that delay out of the
tests (see .github/workflows/main.yml).

Each browser saves a screenshot of a blank page, in a new temporary
profile, and the script waits for the image. On Windows, the launched
process may exit before that, when it hands over to the browser.

The script exits with code 1 if a browser was not found, or did not save
its image within TIMEOUT seconds. Each failure is also written as a warning
of GitHub Actions. The workflow then goes on, and the tests still run.
"""

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from html2image import Html2Image

# Seconds, for each browser, from the start of its lookup. The three
# browsers stay under the 5 minutes of the step.
TIMEOUT = 90


def command(browser, executable, profile, image):
    if browser == 'firefox':
        return [
            executable, '--headless', '-no-remote', '--new-instance',
            '--profile', profile, '--screenshot', image, 'about:blank',
        ]
    return [
        executable, '--headless=new', f'--user-data-dir={profile}',
        '--no-first-run', '--no-default-browser-check',
        f'--screenshot={image}', 'about:blank',
    ]


def stop(process):
    """Stop `process` and the processes that it started."""
    if os.name == 'nt':
        subprocess.run(
            ['taskkill', '/PID', str(process.pid), '/T', '/F'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        # The group may be gone already.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def failed(message):
    print(f'::warning::Warm-up of the browsers: {message}')
    return False


def warm_up(browser):
    """Start `browser` and wait for it to save its image. Return True if it
    did within TIMEOUT seconds."""
    started = time.monotonic()
    deadline = started + TIMEOUT
    try:
        executable = Html2Image(browser=browser).browser.executable
    except FileNotFoundError as error:
        return failed(f'{browser} was not found ({error})')

    profile = tempfile.mkdtemp(prefix='html2image_warm_up_')
    image = os.path.join(profile, 'warm_up.png')
    process = subprocess.Popen(
        command(browser, executable, profile, image),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        # On Linux and macOS, `stop()` will stop the whole group.
        start_new_session=os.name != 'nt',
    )
    try:
        while not (os.path.isfile(image) and os.path.getsize(image)):
            if process.poll():
                return failed(
                    f'{browser} exited with code {process.returncode} '
                    'without saving its image'
                )
            if time.monotonic() >= deadline:
                stop(process)
                return failed(
                    f'{browser} saved no image within {TIMEOUT} seconds, '
                    'and was stopped'
                )
            time.sleep(0.2)
        # The profile can be deleted once the browser has exited.
        try:
            process.wait(timeout=max(1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            stop(process)
    finally:
        shutil.rmtree(profile, ignore_errors=True)

    duration = time.monotonic() - started
    print(f'{browser}: image saved after {duration:.1f}s ({executable})')
    return True


def main():
    results = [warm_up(browser) for browser in ('chrome', 'edge', 'firefox')]
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main())
