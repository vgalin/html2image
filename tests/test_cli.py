import sys

import html2image.cli as cli


def test_cli_forwards_cdp_port_for_chrome(monkeypatch):
    captured = {}

    class FakeHtml2Image:
        def __init__(self, **kwargs):
            captured["init_kwargs"] = kwargs
            self.browser = type("FakeBrowser", (), {})()

        def screenshot(self, **kwargs):
            captured["screenshot_kwargs"] = kwargs
            return ["fake.png"]

    monkeypatch.setattr(cli, "Html2Image", FakeHtml2Image)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hti",
            "--browser",
            "chrome",
            "--cdp-port",
            "9555",
            "--url",
            "https://example.com",
            "--quiet",
        ],
    )

    cli.main()

    assert captured["init_kwargs"]["browser"] == "chrome"
    assert captured["init_kwargs"]["browser_cdp_port"] == 9555


def test_cli_does_not_forward_cdp_port_for_chrome_headless(
    monkeypatch, capsys
):
    captured = {}

    class FakeHtml2Image:
        def __init__(self, **kwargs):
            captured["init_kwargs"] = kwargs
            self.browser = type("FakeBrowser", (), {})()

        def screenshot(self, **kwargs):
            captured["screenshot_kwargs"] = kwargs
            return ["fake.png"]

    monkeypatch.setattr(cli, "Html2Image", FakeHtml2Image)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hti",
            "--browser",
            "chrome-headless",
            "--cdp-port",
            "9555",
            "--url",
            "https://example.com",
            "--quiet",
        ],
    )

    cli.main()

    assert captured["init_kwargs"]["browser"] == "chrome-headless"
    assert "browser_cdp_port" not in captured["init_kwargs"]

    stdout = capsys.readouterr().out
    assert "might not be a CDP browser" in stdout
