"""TEMPORARY diagnostics for the macOS failure of PR 218. To be removed.

Each variant prints a timeline of the CDP commands, and never fails.
"""

import os
import time

import pytest
from PIL import Image

from html2image import Html2Image
from html2image.browsers import chrome_cdp

POPUP = " window.open('about:blank', '_blank', 'width=200,height=200');"


def alert(ms):
    return " setTimeout(() => alert('still there'), %d);" % ms


def first(body):
    return (
        '<body style="margin:0;background:rgb(255,0,0)"><script>'
        "onload = () => {" + body + " }</script>"
    )


GREEN_SLOW = (
    '<body style="margin:0;background:rgb(0,255,0)"><script>'
    "const end = Date.now() + 1000; while (Date.now() < end) {}</script>"
)
BLUE_PAGE = '<body style="margin:0;background:rgb(0,0,255)"></body>'

VARIANTS = {
    "as_is": (first(POPUP + alert(300)), None),
    "alert_only": (first(alert(300)), None),
    "popup_only": (first(POPUP), None),
    "alert_5s": (first(POPUP + alert(5000)), None),
    "window_flags": (
        first(POPUP + alert(300)),
        ["--hide-scrollbars"] + chrome_cdp.WINDOW_FLAGS,
    ),
}

CASES = [
    ("chrome", variant, repeat)
    for variant in VARIANTS for repeat in range(3)
] + [("edge", "as_is", repeat) for repeat in range(2)]


@pytest.mark.parametrize("browser,variant,repeat", CASES)
def test_diag(browser, variant, repeat, tmp_path, monkeypatch):
    page1, flags = VARIANTS[variant]
    try:
        hti = Html2Image(
            browser=browser, output_path=str(tmp_path),
            disable_logging=True, custom_flags=flags,
        )
    except FileNotFoundError:
        pytest.skip("not installed")
    b = hti.browser
    t0 = time.perf_counter()
    events, names = [], {}

    def note(*what):
        events.append((time.perf_counter() - t0,) + what)

    send, wait, nav = b.cdp_send, b._wait_for_result, b._navigate
    leave, open_private, close = (
        b._leave_page, b._open_private_page, b._close_page
    )

    def cdp_send(method, **params):
        msg_id = send(method, **params)
        names[msg_id] = method
        note("send", method, msg_id)
        return msg_id

    def wait_for_result(msg_id, timeout=chrome_cdp.CDP_TIMEOUT):
        try:
            result = wait(msg_id, timeout)
        except Exception as error:
            note("FAILED", names.get(msg_id), msg_id, type(error).__name__)
            raise
        note("answer", names.get(msg_id), msg_id)
        return result

    def navigate(url):
        result = nav(url)
        note("LOADED", url[-30:])
        return result

    def wrapped(name, function):
        def call(*args, **kwargs):
            note("BEGIN", name)
            try:
                return function(*args, **kwargs)
            finally:
                note("END", name)
        return call

    monkeypatch.setattr(b, "cdp_send", cdp_send)
    monkeypatch.setattr(b, "_wait_for_result", wait_for_result)
    monkeypatch.setattr(b, "_navigate", navigate)
    monkeypatch.setattr(b, "_leave_page", wrapped("leave_page", leave))
    monkeypatch.setattr(
        b, "_open_private_page", wrapped("open_private_page", open_private)
    )
    monkeypatch.setattr(b, "_close_page", wrapped("close_page", close))

    outcome = "ok"
    try:
        hti.screenshot(
            html_str=[page1, GREEN_SLOW, BLUE_PAGE],
            save_as=["red.png", "green.png", "blue.png"], size=(100, 100),
        )
    except Exception as error:
        outcome = "%s: %s" % (type(error).__name__, error)
    total = time.perf_counter() - t0
    colors = {
        name: Image.open(os.path.join(tmp_path, name)).convert("RGB")
        .getpixel((50, 50))
        for name in sorted(os.listdir(tmp_path)) if name.endswith(".png")
    }
    print("\n=== DIAG %s %s #%d: %.1fs, %s, files %s" % (
        browser, variant, repeat, total, outcome, colors))
    for event in events:
        print("  %7.3f %s" % (event[0], " ".join(map(str, event[1:]))))
